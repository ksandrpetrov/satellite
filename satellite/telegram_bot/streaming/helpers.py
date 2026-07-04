"""Streaming reply text chunking and draft helpers."""

from __future__ import annotations

import logging
import re
from typing import Literal

from ...presentation.rich import (
    RICH_MESSAGE_SAFETY_CAP,
    _safe_html_prefix,
    rich_blocks_for_streaming,
    truncate_rich_html,
)

log = logging.getLogger(__name__)

_RevealMode = Literal["auto", "blocks", "chars"]

# Throttle: Telegram бьёт по rate-limit'у уже на ~1 update/s, а draft-анимация
# выглядит «дёрганой» при < 0.2 s между кадрами. Дросселируем посредине.
_MIN_DRAFT_INTERVAL_SEC = 0.28
_MIN_DRAFT_CHAR_DELTA = 24
_TELEGRAM_TEXT_LIMIT = 4096

# Typewriter: кадры реже ~0.2 s — клиент не успевает дорисовать анимацию
# предыдущего кадра, и «печать» дёргается. Чтобы воркер-пул хендлеров не
# блокировался дольше ~2 с, кадров не больше _TYPEWRITER_MAX_FRAMES.
_TYPEWRITER_MAX_FRAMES = 9
_TYPEWRITER_BLOCK_MAX_FRAMES = 12
_TYPEWRITER_BLOCK_HERO_BLOCKS = 2
_TYPEWRITER_MIN_CHUNK = 24
_TYPEWRITER_FRAME_INTERVAL_SEC = 0.22
_TYPEWRITER_MIN_TEXT_LEN = 60  # короче — не имеет смысла «печатать»

# Rich-typewriter: блоки с состоянием/структурой появляются только целиком —
# полуоткрытый <details>/<table>/<ul> промаргивает свёрнутым или пустым.
_RICH_ATOMIC_PREFIXES = ("<details", "<table", "<ul", "<ol")
_RICH_TEXT_SUBCHUNK = 56  # длинные текстовые блоки дорезаем по словам этим шагом

# Теги rich message, которых нет в legacy parse_mode=HTML: такой контент
# нельзя отправлять в plain-черновик — Telegram ответит 400.
_RICH_ONLY_TAG_RE = re.compile(
    r"</?(?:details|summary|table|thead|tbody|tr|th|td|h[1-6]|ul|ol|li|hr|time|mark|p|"
    r"blockquote|cite|tg-pullquote|tg-reference|tg-thinking|u|s|spoiler|sub|sup|code)\b",
    re.IGNORECASE,
)

# Описания/коды, при которых черновики недоступны — переходим на legacy.
_DRAFT_UNAVAILABLE_MARKERS = (
    "sendmessagedraft",
    "sendrichmessagedraft",
    "textdraft",
    "method is not found",
    "method not found",
    "unknown method",
    "not implemented",
)

# Маркер «пустой text не разрешён» — Bot API < 10.0 (с 8 мая 2026 разрешён).
_EMPTY_TEXT_REJECTED_MARKERS = (
    "text is empty",
    "message text is empty",
    "text must be non-empty",
)

# Регулярки HTML-safe нарезки.
_HTML_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9]*)(\s[^<>]*)?>")
_HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[a-zA-Z]+);")


def _draft_unavailable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _DRAFT_UNAVAILABLE_MARKERS)


def _empty_text_rejected(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _EMPTY_TEXT_REJECTED_MARKERS)


def _stable_draft_id(*, chat_id: int, seed: int) -> int:
    """Ненулевой draft_id для анимации обновлений одного ответа.

    Telegram анимирует обновления только при совпадающем ``draft_id``;
    разные сессии должны получать разные id, иначе анимации перепутаются.
    """
    mixed = (int(chat_id) * 1_000_003) ^ int(seed)
    return (mixed % 2_147_483_646) + 1


def _safe_slice(text: str, length: int) -> str:
    """Префикс длиной ≤ ``length``, не рвущий HTML-теги и сущности.

    Если внутри ``[0, length)`` оказался не закрытый ``<...`` или ``&...``,
    отступаем до начала этой конструкции. Дополнительно закрываем висящие
    парные теги (``<b><i>...``), чтобы Telegram не отверг сообщение.
    """
    if length >= len(text):
        return text
    cut = length

    last_lt = text.rfind("<", 0, cut)
    last_gt = text.rfind(">", 0, cut)
    if last_lt > last_gt:
        cut = last_lt

    last_amp = text.rfind("&", 0, cut)
    last_semi = text.rfind(";", 0, cut)
    if last_amp > last_semi and cut - last_amp <= 10:
        cut = last_amp

    if cut <= 0:
        return ""

    prefix = text[:cut]
    return _close_open_tags(prefix)


def _close_open_tags(html_text: str) -> str:
    """Закрывает незакрытые парные теги (``<b>foo`` → ``<b>foo</b>``).

    Telegram парсит крайне строго; невалидный HTML → 400 BAD REQUEST и
    промежуточный кадр пропадает. Закрываем по LIFO-стеку.
    """
    stack: list[str] = []
    for match in _HTML_TAG_RE.finditer(html_text):
        closing, tag = match.group(1), match.group(2).lower()
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] == tag:
                    del stack[i]
                    break
        else:
            stack.append(tag)
    if not stack:
        return html_text
    return html_text + "".join(f"</{tag}>" for tag in reversed(stack))


def _clip_text(text: str, *, rich: bool) -> str:
    limit = RICH_MESSAGE_SAFETY_CAP if rich else _TELEGRAM_TEXT_LIMIT
    if len(text) <= limit:
        return text
    if rich:
        return truncate_rich_html(text, max_len=limit)
    return _clip_telegram_text(text)


def _clip_telegram_text(text: str) -> str:
    """Усекает текст до Telegram-лимита 4096, не разрывая HTML-теги/сущности.

    Закрывающие теги, добавленные ``_safe_slice``/``_close_open_tags``, могут
    «съесть» несколько символов сверху — поэтому подбираем cut итеративно.
    """
    if len(text) <= _TELEGRAM_TEXT_LIMIT:
        return text
    budget = _TELEGRAM_TEXT_LIMIT - 1  # резервируем под "…"
    cut = budget
    for _ in range(8):
        candidate = _safe_slice(text, cut) + "…"
        if len(candidate) <= _TELEGRAM_TEXT_LIMIT:
            return candidate
        cut = max(0, cut - (len(candidate) - _TELEGRAM_TEXT_LIMIT) - 4)
    return text[:_TELEGRAM_TEXT_LIMIT]


def _snap_to_word_end(text: str, cut: int) -> int:
    """Двигает позицию реза вперёд до конца текущего слова.

    Обрыв на полуслове заставляет клиент перевёрстывать хвост строки на
    каждом кадре — текст «дёргается». Кадр допечатывает слово целиком.
    """
    while cut < len(text) and not text[cut].isspace():
        cut += 1
    return cut


def _append_growing(frames: list[str], candidate: str) -> None:
    """Добавляет кадр, только если он строго длиннее предыдущего."""
    if candidate and len(candidate) > len(frames[-1] if frames else ""):
        frames.append(candidate)


def _evenly_capped(frames: list[str], limit: int) -> list[str]:
    """Равномерно прореживает кадры до ``limit``, сохраняя последний."""
    if len(frames) <= limit:
        return frames
    picked = sorted({round((i + 1) * len(frames) / limit) - 1 for i in range(limit)})
    return [frames[i] for i in picked]


def _rich_block_stagger_chunks(html_text: str) -> list[str]:
    """Кадры typewriter: hero-блоки целиком, затем по одному блоку."""
    blocks = rich_blocks_for_streaming(html_text)
    if not blocks:
        return []
    hero_count = min(_TYPEWRITER_BLOCK_HERO_BLOCKS, len(blocks))
    frames: list[str] = []
    prefix = ""
    if hero_count:
        prefix = "".join(blocks[:hero_count])
        _append_growing(frames, prefix)
    for block in blocks[hero_count:]:
        prefix += block
        _append_growing(frames, prefix)
    if frames and frames[-1] == html_text:
        frames.pop()
    return _evenly_capped(frames, _TYPEWRITER_BLOCK_MAX_FRAMES)


def _rich_typewriter_chunks(html_text: str) -> list[str]:
    """Кадры rich-typewriter: целые блоки; длинные текстовые — по словам.

    Резать rich HTML по символам нельзя: полуоткрытый ``<details>`` /
    ``<table>`` промаргивает то свёрнутым, то пустым блоком. Поэтому кадр —
    это завершённые блоки целиком, а длинные ``<p>``/``<h*>`` дорезаются по
    границам слов через ``_safe_html_prefix``.
    """
    frames: list[str] = []
    prefix = ""
    for block in rich_blocks_for_streaming(html_text):
        atomic = block.lstrip().lower().startswith(_RICH_ATOMIC_PREFIXES)
        if not atomic and len(block) > _RICH_TEXT_SUBCHUNK * 2:
            cursor = _RICH_TEXT_SUBCHUNK
            while cursor < len(block):
                cut = _snap_to_word_end(block, cursor)
                if cut >= len(block):
                    break
                piece = _safe_html_prefix(block, cut)
                if piece:
                    _append_growing(frames, prefix + piece)
                cursor = max(cursor + _RICH_TEXT_SUBCHUNK, cut + 1)
        prefix += block
        _append_growing(frames, prefix)
    if frames and frames[-1] == html_text:
        frames.pop()  # полный текст отправит финальная доставка
    return _evenly_capped(frames, _TYPEWRITER_MAX_FRAMES)


def _typewriter_chunks(
    text: str,
    *,
    rich: bool = False,
    reveal_mode: _RevealMode = "auto",
) -> list[str]:
    """Постепенно растущие префиксы текста для эффекта «печатает».

    Plain — рез по границам слов; rich — по завершённым блокам (см.
    ``_rich_typewriter_chunks``). Длина кадров строго растёт: текст
    «дописывается», а не перевёрстывается.
    """
    if len(text) < _TYPEWRITER_MIN_TEXT_LEN:
        return []
    if rich:
        use_blocks = reveal_mode == "blocks" or reveal_mode == "auto"
        if use_blocks:
            stagger = _rich_block_stagger_chunks(text)
            if stagger:
                return stagger
        return _rich_typewriter_chunks(text)
    target_frames = min(_TYPEWRITER_MAX_FRAMES, max(3, len(text) // _TYPEWRITER_MIN_CHUNK))
    step = max(_TYPEWRITER_MIN_CHUNK, len(text) // target_frames)
    frames: list[str] = []
    cursor = step
    while cursor < len(text):
        cut = _snap_to_word_end(text, cursor)
        if cut >= len(text):
            break
        _append_growing(frames, _safe_slice(text, cut))
        cursor = max(cursor + step, cut + 1)
    return frames

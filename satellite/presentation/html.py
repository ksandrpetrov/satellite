"""HTML-разметка для Telegram Bot API (parse_mode=HTML).

Централизует ``<blockquote>``, ``<tg-emoji>`` и ``link_preview_options``,
чтобы хендлеры не собирали теги вручную.

Раньше длинные блоки оборачивались в ``<blockquote expandable="true">`` —
Telegram показывал их свёрнутыми с кнопкой «Показать ещё». По требованию
владельца все «сворачивалки» по умолчанию открыты: ``expandable_blockquote``
теперь возвращает обычный ``<blockquote>`` (виден целиком), а пользователь
при необходимости свернёт цитату штатным жестом клиента.
"""

from __future__ import annotations

import re

# Custom emoji document id'ы для ``<tg-emoji emoji-id="…">``.
#
# Bot API разрешает использовать ``<tg-emoji>`` только тем ботам, что купили
# имя пользователя на Fragment (см. примечание про ``custom_emoji`` entities
# в https://core.telegram.org/bots/api). У «обычного» бота любой id ведёт на
# несуществующий документ, и Telegram отвечает ``Bad Request: DOCUMENT_INVALID``
# на весь ``sendMessage`` — то есть сообщение пользователю не доходит.
#
# Поэтому таблица пустая: ``tg_emoji()`` возвращает голый символ, а
# ``replace_first_char_with_tg_emoji()`` оставляет текст без изменений. Если
# когда-нибудь у бота появятся «свои» custom emoji — сюда можно положить
# реальные id из своего пака. Дополнительная защита (на случай, если тег
# просочится из закэшированного черновика) — ретрай в ``api.py``, который
# распознаёт ``DOCUMENT_INVALID`` и снимает теги.
_TG_EMOJI_IDS: dict[str, str] = {}

_TG_EMOJI_TAG_RE = re.compile(
    r'<tg-emoji emoji-id="\d+">([^<]*)</tg-emoji>',
    re.IGNORECASE,
)

DISABLED_LINK_PREVIEW: dict[str, bool] = {"is_disabled": True}


def blockquote(text: str) -> str:
    """Обычный blockquote (Bot API 7.2). ``text`` — без HTML-тегов снаружи."""
    return f"<blockquote>{text}</blockquote>"


def expandable_blockquote(text: str, *, threshold: int = 3) -> str:
    """Длинный блок в обычной (развёрнутой) цитате Telegram.

    Раньше при ``len(lines) >= threshold`` возвращался ``<blockquote
    expandable="true">`` — Telegram показывал его свёрнутым. Сейчас все
    «сворачивалки» по умолчанию открыты, поэтому возвращается обычный
    ``<blockquote>``: содержимое видно сразу, а свернуть пользователь может
    штатным жестом клиента.

    Имя функции и параметр ``threshold`` оставлены ради совместимости
    с вызывающим кодом (``messages_ru``, ``seagull/render.py``): при
    ``len(lines) < threshold`` блок остаётся обычным текстом без обёртки.
    """
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < threshold:
        return text
    return f"<blockquote>{text}</blockquote>"


def tg_emoji(unicode_char: str) -> str:
    """Оборачивает один символ в ``<tg-emoji emoji-id="…">`` для Premium-анимации.

    Если id неизвестен — возвращает исходный символ без тега.
    """
    emoji_id = _TG_EMOJI_IDS.get(unicode_char)
    if not emoji_id:
        return unicode_char
    return f'<tg-emoji emoji-id="{emoji_id}">{unicode_char}</tg-emoji>'


def strip_tg_emoji_tags(html_text: str) -> str:
    """Убирает ``<tg-emoji>`` — fallback при отказе Telegram."""
    return _TG_EMOJI_TAG_RE.sub(r"\1", html_text)


def strip_expandable_blockquote(html_text: str) -> str:
    """Убирает атрибут ``expandable`` — fallback для старых серверов.

    Сейчас ``expandable_blockquote`` атрибут не выставляет, но функция
    оставлена: пригодится, если в кэшированных черновиках или внешнем
    HTML-вводе всё-таки промелькнёт ``<blockquote expandable …>``.
    """
    return html_text.replace('<blockquote expandable="true">', "<blockquote>").replace(
        "<blockquote expandable>", "<blockquote>"
    )


def link_preview_above(url: str, *, large: bool = True) -> dict[str, object]:
    """``link_preview_options`` с превью над текстом (Bot API 7.0+)."""
    opts: dict[str, object] = {
        "url": url,
        "show_above_text": True,
    }
    if large:
        opts["prefer_large_media"] = True
    return opts


def replace_first_char_with_tg_emoji(text: str, unicode_char: str) -> str:
    """Заменяет первое вхождение ``unicode_char`` на ``tg_emoji`` в строке."""
    if unicode_char not in text:
        return text
    idx = text.index(unicode_char)
    return text[:idx] + tg_emoji(unicode_char) + text[idx + len(unicode_char) :]


def build_copy_text_button(label: str, copy_value: str) -> dict[str, object]:
    """Inline-кнопка ``copy_text`` (Bot API 8.0)."""
    return {
        "text": label,
        "copy_text": {"text": copy_value[:256]},
    }


def strip_bold_tags(html_text: str) -> str:
    """Убирает парные ``<b>`` — для plain fallback в foreign calendars."""
    return html_text.replace("<b>", "").replace("</b>", "")

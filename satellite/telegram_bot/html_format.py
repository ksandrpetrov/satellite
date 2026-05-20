"""HTML-разметка для Telegram Bot API (parse_mode=HTML).

Централизует ``<blockquote>``, ``<blockquote expandable>``, ``<tg-emoji>`` и
``link_preview_options``, чтобы хендлеры не собирали теги вручную.
"""

from __future__ import annotations

import re
from html import escape

# Публичные custom emoji id из стандартного пака Telegram (Bot API 7.0+).
# При отказе API клиент снимает теги и повторяет отправку — см. ``api.py``.
_TG_EMOJI_IDS: dict[str, str] = {
    "🪶": "5447414870739176015",
    "🎉": "5046509860389126442",
    "🔥": "5104841245755180586",
    "✨": "5089460564141278042",
    "❤️": "5159385139981059251",
    "📅": "5432521619644131072",
    "🗓": "5432521619644131072",
    "📊": "5447414870739176015",
    "🔔": "5046509860389126442",
    "📨": "5447414870739176015",
    "🛠": "5447414870739176015",
    "➕": "5089460564141278042",
    "⚙️": "5447414870739176015",
    "🍕": "5046509860389126442",
    "🌤": "5089460564141278042",
    "🌧": "5447414870739176015",
    "❄️": "5159385139981059251",
    "💨": "5104841245755180586",
    "👀": "5447414870739176015",
    "✍️": "5447414870739176015",
    "✅": "5089460564141278042",
}

_TG_EMOJI_TAG_RE = re.compile(
    r'<tg-emoji emoji-id="\d+">([^<]*)</tg-emoji>',
    re.IGNORECASE,
)

DISABLED_LINK_PREVIEW: dict[str, bool] = {"is_disabled": True}


def blockquote(text: str) -> str:
    """Обычный blockquote (Bot API 7.2). ``text`` — без HTML-тегов снаружи."""
    return f"<blockquote>{text}</blockquote>"


def expandable_blockquote(text: str, *, threshold: int = 3) -> str:
    """Expandable blockquote (Bot API 7.4), если ``text`` достаточно длинный.

    ``threshold`` — минимальное число непустых строк (после split по ``\\n``),
    при котором имеет смысл сворачивать блок.
    """
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < threshold:
        return text
    return f'<blockquote expandable="true">{text}</blockquote>'


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
    """Убирает атрибут ``expandable`` — fallback для старых серверов."""
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

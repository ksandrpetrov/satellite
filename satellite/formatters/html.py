"""Neutral HTML formatting facade for user-facing text builders."""

from __future__ import annotations

from ..telegram_bot.html_format import (
    DISABLED_LINK_PREVIEW,
    blockquote,
    build_copy_text_button,
    expandable_blockquote,
    link_preview_above,
    replace_first_char_with_tg_emoji,
    strip_expandable_blockquote,
    strip_tg_emoji_tags,
    tg_emoji,
)


def strip_bold_tags(html_text: str) -> str:
    """Убирает парные ``<b>`` — для plain fallback в foreign calendars."""
    return html_text.replace("<b>", "").replace("</b>", "")


__all__ = [
    "DISABLED_LINK_PREVIEW",
    "blockquote",
    "build_copy_text_button",
    "expandable_blockquote",
    "link_preview_above",
    "replace_first_char_with_tg_emoji",
    "strip_bold_tags",
    "strip_expandable_blockquote",
    "strip_tg_emoji_tags",
    "tg_emoji",
]

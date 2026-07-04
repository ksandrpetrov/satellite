"""Streaming delivery facade."""

from __future__ import annotations

import logging

from .api import TelegramClient
from .streaming.helpers import (
    _close_open_tags,
    _rich_block_stagger_chunks,
    _safe_slice,
    _typewriter_chunks,
)
from .streaming.session import StreamingReply

__all__ = [
    "StreamingReply",
    "_close_open_tags",
    "_rich_block_stagger_chunks",
    "_safe_slice",
    "_typewriter_chunks",
    "open_streaming_reply",
]

log = logging.getLogger(__name__)


def open_streaming_reply(
    telegram: TelegramClient,
    chat_id: int,
    initial_text: str = "",
    *,
    draft_id: int | None = None,
    message_thread_id: int | None = None,
    parse_mode: str | None = "HTML",
    disable_web_page_preview: bool = True,
    chat_action: str | None = "typing",
    rich: bool = False,
) -> StreamingReply:
    """Удобная фабрика (без ``HandlerContext`` — меньше связности).

    Пустой ``initial_text`` (по умолчанию) → нативный «Thinking…» placeholder
    из Bot API 10.0; на старых серверах автоматически заменяется на «⏳».
    """
    return StreamingReply.open(
        telegram,
        chat_id,
        initial_text,
        draft_id=draft_id,
        message_thread_id=message_thread_id,
        parse_mode=parse_mode,
        disable_web_page_preview=disable_web_page_preview,
        chat_action=chat_action,
        rich=rich,
    )

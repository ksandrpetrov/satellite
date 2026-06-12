"""Доставка сообщений: rich с fallback на legacy HTML."""

from __future__ import annotations

import logging
from typing import Any

from .api import TelegramClient, TelegramError, is_rich_message_unavailable
from .rich_message import input_rich_message

log = logging.getLogger(__name__)


def deliver_rich_or_html(
    telegram: TelegramClient,
    chat_id: int | str,
    *,
    rich_html: str,
    fallback_html: str,
    reply_markup: dict | list | str | None = None,
    message_effect_id: str | None = None,
) -> dict[str, Any] | None:
    """``sendRichMessage`` с fallback на legacy ``sendMessage`` HTML."""
    rich_payload = input_rich_message(rich_html)
    try:
        return telegram.send_rich_message(
            chat_id,
            rich_payload,
            reply_markup=reply_markup,
            message_effect_id=message_effect_id,
        )
    except TelegramError as exc:
        if is_rich_message_unavailable(exc):
            log.info("sendRichMessage unavailable, using sendMessage fallback: %s", exc)
        else:
            log.warning("sendRichMessage failed, falling back to sendMessage: %s", exc)
    return telegram.send_message(
        chat_id,
        fallback_html,
        reply_markup=reply_markup,
        message_effect_id=message_effect_id,
    )


def edit_rich_or_html(
    telegram: TelegramClient,
    chat_id: int | str,
    message_id: int,
    *,
    rich_html: str,
    fallback_html: str,
    reply_markup: dict | list | str | None = None,
) -> dict[str, Any] | None:
    """``editMessageText`` с rich_message и fallback на legacy HTML."""
    rich_payload = input_rich_message(rich_html)
    try:
        return telegram.edit_message_rich(
            chat_id,
            message_id,
            rich_payload,
            reply_markup=reply_markup,
        )
    except TelegramError as exc:
        if is_rich_message_unavailable(exc):
            log.info("editMessageRich unavailable, using legacy HTML: %s", exc)
        else:
            log.warning("editMessageRich failed, falling back to legacy HTML: %s", exc)
    return telegram.edit_message_text(
        chat_id,
        message_id,
        fallback_html,
        reply_markup=reply_markup,
    )

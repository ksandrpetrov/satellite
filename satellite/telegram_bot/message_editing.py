"""Безопасное редактирование сообщений с fallback на отправку нового.

Пользовательский сценарий: бот шлёт loading-сообщение, делает работу, а потом
редактирует то же сообщение в итоговый текст — чтобы в чате не оставалось
два сообщения (loading + результат).

Telegram может отказать в редактировании по разным причинам: сообщение слишком
старое, текст совпадает с текущим, сетевая ошибка и т.п. В этом случае мы
не показываем технические детали пользователю, а просто отправляем новое
сообщение с итоговым текстом.

Этот хелпер изолирует ``try/except`` в одном месте, чтобы обработчики команд
оставались декларативными.
"""

from __future__ import annotations

import logging
from typing import Any

from .api import TelegramClient, TelegramError

log = logging.getLogger(__name__)

_UNSET = object()


def edit_or_send_message(
    telegram: TelegramClient,
    chat_id: int,
    message_id: int | None,
    text: str,
    *,
    parse_mode: str | None = "HTML",
    reply_markup: dict | list | str | None = None,
    fallback_reply_markup: dict | list | str | None | object = _UNSET,
    disable_web_page_preview: bool = True,
) -> dict[str, Any] | None:
    """Пытается отредактировать сообщение; если не вышло — шлёт новое.

    ``message_id`` может быть ``None`` (например, если предыдущий
    ``send_message`` упал и id неизвестен) — тогда сразу отправляется новое
    сообщение.

    ``fallback_reply_markup`` нужен для обычной Telegram reply-клавиатуры: её
    нельзя передавать в ``editMessageText``, но нужно сохранить при fallback на
    новое сообщение.

    Ошибки редактирования логируются как ``warning`` и не пробрасываются.
    Ошибки отправки нового сообщения пробрасываются наверх (``TelegramError``),
    чтобы вызывающий код мог как минимум залогировать факт полной недоставки.
    """
    if message_id is not None:
        try:
            return telegram.edit_message_text(
                chat_id,
                message_id,
                text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=disable_web_page_preview,
            )
        except TelegramError as error:
            log.warning("Falling back to new message after edit failed: %s", error)
        except Exception as error:  # noqa: BLE001 - не показываем стек юзеру
            log.warning("Unexpected error editing message, sending new one: %s", error)

    send_reply_markup = reply_markup if fallback_reply_markup is _UNSET else fallback_reply_markup
    return telegram.send_message(
        chat_id,
        text,
        parse_mode=parse_mode,
        reply_markup=send_reply_markup,  # type: ignore[arg-type]
        disable_web_page_preview=disable_web_page_preview,
    )

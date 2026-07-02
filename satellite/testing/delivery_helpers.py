"""Хелперы для assert'ов rich/legacy доставки в handler-тестах."""

from __future__ import annotations

from unittest.mock import MagicMock


def final_message_html(telegram: MagicMock) -> str:
    """HTML финального ответа: ``sendRichMessage`` или fallback ``sendMessage``."""
    if telegram.send_rich_message.called:
        payload = telegram.send_rich_message.call_args[0][1]
        return str(payload["html"])
    assert telegram.send_message.called
    return str(telegram.send_message.call_args[0][1])


def final_reply_markup(telegram: MagicMock):
    """``reply_markup`` из финальной доставки (rich или legacy)."""
    if telegram.send_rich_message.called:
        return telegram.send_rich_message.call_args.kwargs.get("reply_markup")
    return telegram.send_message.call_args.kwargs.get("reply_markup")


def callback_edit_html(telegram: MagicMock) -> str:
    """HTML после edit callback (rich или legacy)."""
    if telegram.edit_message_rich.called:
        payload = telegram.edit_message_rich.call_args[0][2]
        return str(payload["html"])
    assert telegram.edit_message_text.called
    return str(telegram.edit_message_text.call_args[0][2])


def callback_edit_markup(telegram: MagicMock):
    """``reply_markup`` из callback-edit (rich или legacy)."""
    if telegram.edit_message_rich.called:
        return telegram.edit_message_rich.call_args.kwargs.get("reply_markup")
    return telegram.edit_message_text.call_args.kwargs.get("reply_markup")


def callback_edit_was_called(telegram: MagicMock) -> bool:
    return bool(telegram.edit_message_rich.called or telegram.edit_message_text.called)


def sent_messages_text(telegram: MagicMock) -> list[str]:
    """Все тексты из ``sendRichMessage`` / ``sendMessage`` в порядке вызова."""
    texts: list[str] = []
    for call in telegram.send_rich_message.call_args_list:
        texts.append(str(call[0][1]["html"]))
    for call in telegram.send_message.call_args_list:
        texts.append(str(call[0][1]))
    return texts

"""Юнит-тесты потоковой доставки ``sendMessageDraft`` + legacy fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.streaming_delivery import StreamingReply, open_streaming_reply


def _telegram() -> MagicMock:
    tg = MagicMock()
    tg.send_message_draft = MagicMock(return_value=True)
    tg.send_message = MagicMock(return_value={"message_id": 42})
    tg.edit_message_text = MagicMock(return_value={})
    return tg


def test_draft_mode_finishes_with_send_message() -> None:
    tg = _telegram()
    stream = open_streaming_reply(tg, 100, "⏳ loading", draft_id=7)
    stream.push("partial")
    stream.finish("<b>done</b>")

    assert tg.send_message_draft.call_count >= 1
    tg.send_message.assert_called_once()
    assert tg.send_message.call_args[0][1] == "<b>done</b>"
    tg.edit_message_text.assert_not_called()


def test_legacy_fallback_when_draft_unavailable() -> None:
    tg = _telegram()
    tg.send_message_draft = MagicMock(
        side_effect=TelegramError("sendMessageDraft failed: METHOD_NOT_FOUND")
    )
    stream = open_streaming_reply(tg, 200, "⏳ wait", draft_id=9)
    stream.finish("result")

    tg.send_message.assert_called()
    tg.edit_message_text.assert_called_once()
    assert tg.edit_message_text.call_args[0][2] == "result"


def test_legacy_when_draft_disabled_uses_edit_or_send() -> None:
    tg = _telegram()
    tg.send_message_draft = MagicMock(return_value=False)
    tg.edit_message_text = MagicMock(return_value={"message_id": 42})
    stream = StreamingReply.open(tg, 300, "⏳")
    result = stream.finish("ok")
    assert result == {"message_id": 42}
    tg.edit_message_text.assert_called_once_with(
        300, 42, "ok", parse_mode="HTML", reply_markup=None, disable_web_page_preview=True
    )


def test_push_throttles_rapid_small_updates() -> None:
    tg = _telegram()
    stream = open_streaming_reply(tg, 400, "start", draft_id=1)
    tg.send_message_draft.reset_mock()
    stream.push("startx")  # +1 char — below delta
    stream.push("startxy")  # still small
    # Только если прошло время — второй может пройти; первый маленький — skip
    assert tg.send_message_draft.call_count <= 1


def test_dismiss_clears_draft() -> None:
    tg = _telegram()
    stream = open_streaming_reply(tg, 500, "⏳", draft_id=3)
    stream.dismiss()
    last = tg.send_message_draft.call_args
    assert last is not None
    assert last[0][2] == ""

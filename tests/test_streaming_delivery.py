"""Юнит-тесты потоковой доставки ``sendMessageDraft`` + legacy fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.streaming_delivery import (
    StreamingReply,
    _close_open_tags,
    _safe_slice,
    _typewriter_chunks,
    open_streaming_reply,
)


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


def test_dismiss_does_not_resend_empty_draft() -> None:
    """Регрессия: в draft-режиме ``dismiss()`` НЕ шлёт ``sendMessageDraft("")``.

    На Bot API 10.0+ пустой ``text`` рисует нативный «Thinking…» placeholder.
    Если вызвать его в ``dismiss()`` после реальной доставки (например,
    ``sendPhoto`` в недельной аналитике), Telegram выводит фантомный «…»
    баббл под фотографией и держит его весь 30-секундный TTL черновика —
    пользователь видит вторую «Чайка думает» индикацию уже после готового
    отчёта. Поэтому в draft-ветке dismiss НЕ дёргает ``sendMessageDraft``;
    предыдущий статус-черновик Telegram гасит сам по TTL.
    """
    tg = _telegram()
    stream = open_streaming_reply(tg, 500, "⏳", draft_id=3)
    initial_calls = tg.send_message_draft.call_count
    stream.dismiss()
    assert tg.send_message_draft.call_count == initial_calls


def test_dismiss_deletes_legacy_loading_message() -> None:
    """В legacy-режиме dismiss обязан убрать loading-сообщение из чата."""
    tg = _telegram()
    tg.send_message_draft = MagicMock(return_value=False)
    tg.send_message = MagicMock(return_value={"message_id": 777})
    tg.delete_message = MagicMock(return_value=True)
    stream = StreamingReply.open(tg, 600, "⏳")
    stream.dismiss()
    tg.delete_message.assert_called_once_with(600, 777)


def test_native_thinking_placeholder_uses_empty_text() -> None:
    """Пустой initial_text → черновик стартует с text='' (Bot API 10.0 placeholder)."""
    tg = _telegram()
    open_streaming_reply(tg, 700, "", draft_id=11)
    assert tg.send_message_draft.call_args[0][2] == ""


def test_empty_text_rejected_falls_back_to_placeholder() -> None:
    """Старый Bot API (< 10.0): после отказа на text='' пробуем '⏳'."""
    tg = _telegram()
    calls: list[str] = []

    def _draft(_chat_id, _draft_id, text, **_kw):
        calls.append(text)
        if text == "":
            raise TelegramError("Bad Request: message text is empty")
        return True

    tg.send_message_draft = MagicMock(side_effect=_draft)
    stream = open_streaming_reply(tg, 800, "", draft_id=12)
    assert calls == ["", "⏳"]
    stream.finish("done")
    tg.send_message.assert_called_once()


def test_finish_runs_typewriter_in_draft_mode() -> None:
    """В draft-режиме перед финалом происходит несколько растущих кадров."""
    tg = _telegram()
    stream = open_streaming_reply(tg, 900, "⏳", draft_id=13)
    tg.send_message_draft.reset_mock()
    long_text = "Слово " * 60
    stream.finish(long_text, typewriter=True)
    assert tg.send_message_draft.call_count >= 2
    tg.send_message.assert_called_once()
    assert tg.send_message.call_args[0][1] == long_text


def test_finish_skips_typewriter_in_legacy_mode() -> None:
    tg = _telegram()
    tg.send_message_draft = MagicMock(return_value=False)
    tg.edit_message_text = MagicMock(return_value={"message_id": 1})
    stream = StreamingReply.open(tg, 1000, "⏳")
    long_text = "Слово " * 60
    stream.finish(long_text, typewriter=True)
    # Legacy не должен крутить typewriter через черновик: только одна правка.
    tg.send_message_draft.assert_called_once()  # стартовый attempt
    tg.edit_message_text.assert_called_once()


# --- HTML-safe нарезка ------------------------------------------------------


def test_safe_slice_does_not_break_html_tag() -> None:
    text = "Hello <b>bold</b> world"
    # cut посреди '<b>'
    sliced = _safe_slice(text, 7)
    assert "<b" not in sliced or sliced.endswith("</b>")
    assert "</b>" not in sliced or sliced.count("<b>") == sliced.count("</b>")


def test_safe_slice_does_not_break_html_entity() -> None:
    text = "5 &amp; 3 is even"
    # cut внутри '&amp;'
    sliced = _safe_slice(text, 4)
    assert "&" not in sliced or ";" in sliced


def test_safe_slice_closes_open_tags() -> None:
    text = "<b>Hello world</b>"
    sliced = _safe_slice(text, 8)
    assert sliced.count("<b>") == sliced.count("</b>")


def test_close_open_tags_handles_nested_pairs() -> None:
    assert _close_open_tags("<b><i>hi") == "<b><i>hi</i></b>"
    assert _close_open_tags("<b>x</b><i>y") == "<b>x</b><i>y</i>"
    assert _close_open_tags("plain text") == "plain text"


def test_typewriter_chunks_are_monotonic_and_html_safe() -> None:
    text = "<b>Заголовок</b>\n" + ("Длинный текст. " * 30)
    chunks = _typewriter_chunks(text)
    assert len(chunks) >= 2
    for prev, curr in zip(chunks, chunks[1:]):
        assert len(curr) >= len(prev)
    for chunk in chunks:
        assert chunk.count("<b>") == chunk.count("</b>")


def test_typewriter_chunks_skipped_on_short_text() -> None:
    assert _typewriter_chunks("hi") == []
    assert _typewriter_chunks("x" * 50) == []


def test_typewriter_chunks_rich_use_character_steps() -> None:
    html = "<h2>Title</h2><p>" + ("word " * 40) + "</p>"
    chunks = _typewriter_chunks(html, rich=True)
    assert len(chunks) >= 3
    for prev, curr in zip(chunks, chunks[1:]):
        assert len(curr) > len(prev)
    assert chunks[-1].count("<h2>") == chunks[-1].count("</h2>")


def test_clip_to_telegram_limit_preserves_html() -> None:
    long = "<b>" + ("a" * 5000) + "</b>"
    tg = _telegram()
    stream = StreamingReply.open(tg, 1100, "⏳", draft_id=14)
    tg.send_message_draft.reset_mock()
    stream.push(long)
    sent = tg.send_message_draft.call_args[0][2]
    assert len(sent) <= 4096
    # HTML-теги остались сбалансированы
    assert sent.count("<b>") == sent.count("</b>")

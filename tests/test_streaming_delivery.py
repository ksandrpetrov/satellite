"""Юнит-тесты потоковой доставки ``sendMessageDraft`` + legacy fallback."""

from __future__ import annotations

from unittest.mock import MagicMock

from satellite.telegram_bot.api import TelegramError
from satellite.telegram_bot.streaming_delivery import (
    StreamingReply,
    _close_open_tags,
    _rich_block_stagger_chunks,
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


def test_action_only_mode_skips_preview_and_sends_final_message() -> None:
    """Бинарный результат ждём через chat action, без текстового draft/loading."""
    tg = _telegram()
    tg.send_chat_action = MagicMock(return_value=True)

    stream = open_streaming_reply(
        tg,
        350,
        "этот текст не должен появиться",
        chat_action="upload_photo",
        use_draft=False,
    )

    tg.send_message_draft.assert_not_called()
    tg.send_message.assert_not_called()
    tg.send_chat_action.assert_called_once_with(
        350,
        "upload_photo",
        message_thread_id=None,
    )

    stream.finish("ошибка", typewriter=False)

    tg.send_message.assert_called_once()
    assert tg.send_message.call_args[0][1] == "ошибка"
    tg.edit_message_text.assert_not_called()


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


def test_rich_open_uses_tg_thinking_draft() -> None:
    """Rich-режим без initial_text → ``<tg-thinking>`` в ``sendRichMessageDraft``."""
    tg = _telegram()
    tg.send_rich_message_draft = MagicMock(return_value=True)
    open_streaming_reply(tg, 701, "", draft_id=15, rich=True)
    tg.send_rich_message_draft.assert_called_once()
    rich_html = tg.send_rich_message_draft.call_args[0][2]["html"]
    assert rich_html.startswith("<tg-thinking>")
    assert "Чайка думает" in rich_html


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


def test_typewriter_chunks_cut_on_word_boundaries() -> None:
    """Кадры допечатывают слово целиком — обрыв на полуслове дёргает вёрстку."""
    text = "слово " * 40
    chunks = _typewriter_chunks(text)
    assert chunks
    for chunk in chunks:
        assert text[len(chunk)].isspace()


def test_rich_block_stagger_chunks_reveal_by_block() -> None:
    html = "<h2>T</h2><p>intro</p><hr><p>tail</p>"
    chunks = _rich_block_stagger_chunks(html)
    assert len(chunks) >= 2
    assert chunks[0] == "<h2>T</h2><p>intro</p>"
    for prev, curr in zip(chunks, chunks[1:]):
        assert len(curr) > len(prev)


def test_typewriter_chunks_rich_block_mode_prefers_stagger() -> None:
    html = "<h2>T</h2><p>a</p><p>b</p><p>c</p>" + ("<p>x</p>" * 6)
    chunks = _typewriter_chunks(html, rich=True, reveal_mode="blocks")
    assert len(chunks) >= 2
    assert chunks[0].startswith("<h2>")


def test_typewriter_chunks_rich_grow_by_blocks_and_words() -> None:
    """Rich-кадры: длинные тексты растут по словам, блоки появляются целиком."""
    html = "<h2>Title</h2><p>" + ("word " * 40) + "</p>"
    chunks = _typewriter_chunks(html, rich=True)
    assert len(chunks) >= 3
    for prev, curr in zip(chunks, chunks[1:]):
        assert len(curr) > len(prev)
    for chunk in chunks:
        assert chunk.count("<h2>") == chunk.count("</h2>")
        assert chunk.count("<p>") == chunk.count("</p>")
    assert chunks[-1] != html  # полный текст отправляет финальная доставка


def test_typewriter_chunks_rich_never_split_details_or_table() -> None:
    """Сворачиваемые блоки и таблицы не вскрываются посреди кадра.

    Полуоткрытый ``<details>`` промаргивает то свёрнутым, то пустым блоком —
    источник «мигания» в /upcoming. Каждый кадр обязан содержать details и
    table только целиком.
    """
    html = (
        "<h2>Ближайшие события</h2>"
        "<details open><summary>Сегодня — 3</summary>"
        "<ul><li>a</li><li>b</li><li>c</li></ul></details>"
        "<details open><summary>Завтра — 2</summary>"
        "<ul><li>d</li><li>e</li></ul></details>"
        "<table><tr><th>Тип</th><th>Время</th></tr><tr><td>Занято</td><td>4 ч</td></tr></table>"
        "<p>хвостовая строка дайджеста</p>"
    )
    chunks = _typewriter_chunks(html, rich=True)
    assert chunks
    for chunk in chunks:
        assert chunk.count("<details") == chunk.count("</details>")
        assert chunk.count("<table") == chunk.count("</table>")
        assert chunk.count("<ul") == chunk.count("</ul>")


def test_rich_typewriter_does_not_flash_legacy_fallback() -> None:
    """Регрессия: rich-draft умер на кадре → никаких plain-кадров со старым оформлением.

    Раньше ``_draft_text`` подставлял в кадры typewriter полный
    ``_last_fallback_html`` (старый вариант с expandable blockquote) — он
    «промаргивал» поверх будущего rich-сообщения. Теперь такие кадры просто
    пропускаются, финал остаётся rich.
    """
    tg = _telegram()
    tg.send_rich_message_draft = MagicMock(return_value=True)
    tg.send_rich_message = MagicMock(return_value={"message_id": 7})
    stream = open_streaming_reply(tg, 1200, "⏳ статус", draft_id=21, rich=True)
    tg.send_message_draft.reset_mock()
    tg.send_rich_message_draft.side_effect = TelegramError(
        "Bad Request: method sendRichMessageDraft is not found"
    )
    rich_html = "<h2>Список</h2>" + "".join(
        f"<p>Пункт {i} — длинная строка списка событий.</p>" for i in range(8)
    )
    legacy_html = "<b>Старый вариант</b><blockquote expandable>тело</blockquote>"

    stream.finish(rich_html, fallback_html=legacy_html, rich=True)

    plain_frames = [call.args[2] for call in tg.send_message_draft.call_args_list]
    assert legacy_html not in plain_frames
    assert all("<p>" not in frame for frame in plain_frames)
    tg.send_rich_message.assert_called_once()


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

"""Тесты HTML-хелперов для Telegram."""

from __future__ import annotations

from satellite.telegram_bot.html_format import (
    blockquote,
    build_copy_text_button,
    expandable_blockquote,
    strip_expandable_blockquote,
    strip_tg_emoji_tags,
    tg_emoji,
)


def test_blockquote_wraps_text() -> None:
    assert blockquote("hello") == "<blockquote>hello</blockquote>"


def test_expandable_blockquote_when_enough_lines() -> None:
    """Сворачивалки теперь открыты по умолчанию.

    Длинный блок остаётся в обычной цитате (виден целиком), чтобы пользователь
    не разворачивал его вручную; свернуть его можно штатным жестом клиента.
    """

    body = "a\nb\nc\nd"
    out = expandable_blockquote(body, threshold=3)
    assert out == f"<blockquote>{body}</blockquote>"
    assert 'expandable="true"' not in out
    assert "<blockquote expandable" not in out


def test_expandable_blockquote_skips_short_text() -> None:
    assert expandable_blockquote("one line", threshold=3) == "one line"


def test_tg_emoji_falls_back_to_plain_char_when_unregistered() -> None:
    """Без зарегистрированного ``emoji-id`` возвращаем голый символ.

    ``<tg-emoji>`` доступен только ботам с купленным на Fragment именем; для
    «обычного» бота любой id ведёт на DOCUMENT_INVALID и ломает sendMessage.
    Поэтому таблица сейчас пустая и любое обращение к ``tg_emoji()`` отдаёт
    исходный символ без обёртки.
    """
    out = tg_emoji("🪶")
    assert out == "🪶"
    assert "<tg-emoji" not in out


def test_strip_tg_emoji_tags() -> None:
    raw = '<tg-emoji emoji-id="123">🪶</tg-emoji> hi'
    assert strip_tg_emoji_tags(raw) == "🪶 hi"


def test_strip_expandable_blockquote() -> None:
    raw = '<blockquote expandable="true">x</blockquote>'
    assert strip_expandable_blockquote(raw) == "<blockquote>x</blockquote>"


def test_build_copy_text_button_truncates() -> None:
    long = "x" * 300
    btn = build_copy_text_button("copy", long)
    assert len(btn["copy_text"]["text"]) == 256

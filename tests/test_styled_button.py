"""Юнит-тесты цветных inline-кнопок."""

from __future__ import annotations

from satellite.messages_ru import styled_button


def test_styled_button_without_style() -> None:
    btn = styled_button("OK", "cb:ok")
    assert btn == {"text": "OK", "callback_data": "cb:ok"}


def test_styled_button_with_success_style() -> None:
    btn = styled_button("Да", "cb:yes", style="success")
    assert btn["style"] == "success"

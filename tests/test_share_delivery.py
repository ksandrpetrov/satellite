"""Клавиатура и URL Web App «Поделиться»."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

from satellite.messages_ru import BUTTON_SHARE, SHARE_KIND_PLAN, build_share_keyboard
from satellite.telegram_bot.handlers.delivery import webapp_share_url
from satellite.web.connect_token import ConnectTokenStore


@dataclass
class _Webapp:
    base_url: str = "https://example.test/connect"


def test_build_share_keyboard():
    kb = build_share_keyboard("https://example.test/share#kind=plan")
    assert kb["inline_keyboard"][0][0]["text"] == BUTTON_SHARE
    assert kb["inline_keyboard"][0][0]["web_app"]["url"].startswith("https://")


def test_webapp_share_url_with_token(tmp_path):
    ctx = MagicMock()
    ctx.webapp = _Webapp()
    ctx.connect_tokens = ConnectTokenStore(storage_path=tmp_path / "tokens.json")
    url = webapp_share_url(ctx, 42, kind=SHARE_KIND_PLAN, mode="today")
    assert "/share/" in url
    assert "kind=plan" in url
    assert "mode=today" in url

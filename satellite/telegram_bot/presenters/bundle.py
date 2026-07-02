"""ScreenBundle — пара rich + legacy HTML для единой доставки."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScreenBundle:
    """Пара rich + legacy HTML и опциональная клавиатура."""

    rich_html: str
    fallback_html: str
    reply_markup: dict | None = None

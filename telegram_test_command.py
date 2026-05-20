"""Entry-point: интерактивный Telegram-бот (long-polling).

Тонкая обёртка над `satellite.services.run_bot()`. Конкретная логика —
в пакете `satellite.telegram_bot`.
"""

from __future__ import annotations

import sys

from satellite.services import bot_cli


def main() -> None:
    bot_cli(sys.argv[1:])


if __name__ == "__main__":
    main()

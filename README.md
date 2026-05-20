# Чайка

Production Telegram-бот для календарных дайджестов из Mail.ru Calendar.

Чайка показывает встречи на сегодня, завтра и послезавтра, умеет отправлять
автоматический дайджест по персональному расписанию, добавляет погодный блок и
говорит с пользователем короткими текстами в своем стиле.

Каждый пользователь подключает свой календарь через Telegram Web App; доступ
к боту выдаётся админом после заявки. Глобальных Mail.ru-паролей и карты
`USER_CALENDAR_MAP` больше нет.

## Возможности

- Команды `td`, `tm`, `dat`.
- Команды меню `/today`, `/tomorrow`, `/aftertomorrow`, `/after_tomorrow`.
- `/start`, `/help`, `/settings`.
- Заявка на доступ и одобрение админом (`ADMIN_TELEGRAM_IDS`, `/pending`).
- Подключение календаря Mail.ru через Telegram Web App (per-user credentials).
- Подписка и отключение дайджеста.
- Настройки дайджеста через inline-кнопки.
- Дни отправки: `weekdays` или `all_days`.
- Время отправки в формате `HH:MM`, по умолчанию `09:00 Europe/Moscow`.
- CalDAV per-user с шифрованием токенов (Fernet).
- Расчет занятости, свободного времени, пересечений и обеда.
- Open-Meteo погода с кэшем и безопасным fallback.
- `sendChatAction` во время долгих операций.
- Паттерн `loading message -> editMessageText`.
- Thread-safe JSON storage настроек и пользователей.

## Быстрый старт

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
cp .env.example .env
```

Заполните `.env` (минимум — см. [docs/configuration.md](docs/configuration.md)),
затем запустите long-polling бота:

```bash
python telegram_test_command.py
```

Запустить тесты:

```bash
python -m pytest
```

## Запуск на сервере

На VPS или домашнем сервере бот обычно крутится как systemd-сервис: один процесс
long-polling, автоперезапуск при падении, логи в `logs/bot.log` и `journalctl`.

Перед production настройте reverse proxy на `WEBAPP_BASE_URL` →
`WEBAPP_HOST:WEBAPP_PORT` (см. [docs/operations.md](docs/operations.md)).

После обновления кода перезапустите уже запущенный сервис:

```bash
sudo systemctl restart satellite-bot.service
```

Пошаговая установка: [docs/operations.md](docs/operations.md#запуск-на-сервере).

## Главное про конфиг

Минимум для interactive-бота:

```env
TELEGRAM_BOT_TOKEN=123456:your-bot-token
TOKEN_ENCRYPTION_KEY=<fernet-key>
ADMIN_TELEGRAM_IDS=111111111
WEBAPP_BASE_URL=https://your-domain.example/connect
```

Полная карта переменных: [docs/configuration.md](docs/configuration.md).

## Основной entrypoint

- `telegram_test_command.py` — production long-polling бот.

Дайджест отправляется фоновым шедулером внутри того же процесса по
персональному расписанию каждого пользователя из `logs/subscriptions.json`.

## Документация

- [Архитектура](docs/architecture.md)
- [Конфигурация](docs/configuration.md)
- [Telegram UX](docs/telegram-ux.md)
- [Эксплуатация и деплой](docs/operations.md)
- [Тестирование](docs/testing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [AGENTS.md](AGENTS.md) — карта модулей и инварианты для правок кода и AI-агентов

Тесты в CI: Python 3.11, `pytest` и compile-check (см. `.github/workflows/test.yml`).

## Runtime-файлы

Все состояние процесса лежит в `logs/`:

- `bot.log`;
- `bot.lock`;
- `telegram-offset.json`;
- `subscriptions.json` — настройки дайджеста;
- `users.json` — статус доступа и зашифрованные CalDAV-credentials.

`logs/`, `.env`, `venv/` не должны попадать в репозиторий.

## Короткая диагностика

- Бот не стартует: проверьте `TELEGRAM_BOT_TOKEN`, `TOKEN_ENCRYPTION_KEY`,
  `ADMIN_TELEGRAM_IDS`, `WEBAPP_BASE_URL`.
- Команды не работают: пользователь должен быть `approved` и подключить календарь
  (`calendar_status=connected` в `logs/users.json`).
- Нет погоды: `WEATHER_ENABLED=true` и координаты.
- Дайджест не приходит: `/settings`, `digest_enabled`, день недели, время,
  `logs/subscriptions.json`.

Подробнее: [docs/troubleshooting.md](docs/troubleshooting.md).

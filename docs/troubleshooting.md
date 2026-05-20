# Troubleshooting

## Бот не запускается

### Missing / invalid env vars

Проверьте `.env`:

```env
TELEGRAM_BOT_TOKEN=...
TOKEN_ENCRYPTION_KEY=...
ADMIN_TELEGRAM_IDS=...
WEBAPP_BASE_URL=...
```

`MAIL_LOGIN`, `USER_CALENDAR_MAP` и `TARGET_CALENDAR_NAME` больше не используются.

**ADMIN_TELEGRAM_IDS** — только **числовой** Telegram user id (`123456789`), через
запятую. `@username` не подходит: бот проигнорирует его и упадёт с
`ADMIN_TELEGRAM_IDS: нет ни одного числового id`. Свой id: [@userinfobot](https://t.me/userinfobot).

**TELEGRAM_BOT_TOKEN** — полный токен от @BotFather (`123456789:AAH...`). Значения
`123456:your-bot-token` из `.env.example` дают HTTP 401 Unauthorized.

**WEBAPP_BASE_URL** — реальный HTTPS, не `https://your-domain.example/connect`.

### Неверный ключ шифрования

`TOKEN_ENCRYPTION_KEY` должен быть валидным Fernet-ключом (32-byte urlsafe base64).
Сгенерировать заново — см. [configuration.md](configuration.md).

После смены ключа расшифровка старых записей в `logs/users.json` падает —
пользователям нужно переподключить календарь в Web App.

### Другой экземпляр уже работает

Если в логе есть сообщение про lock, уже запущен другой процесс бота.

Проверьте процессы и остановите лишний экземпляр. Не удаляйте `bot.lock`, пока
не убедитесь, что процесс действительно завершен.

## Бот молчит в Telegram

Проверьте:

- пользователь написал боту в личку;
- запись в `logs/users.json` существует и `status=approved`;
- `calendar_status=connected`, `encrypted_credentials` не пустой;
- для команд плана — `UserRecord.has_calendar` истинно;
- бот запущен с нужным `.env` и не упал при старте (Web App URL, Fernet key).

`/start` и `/help` отвечают всем. Остальные сценарии для пользователей без
подключённого календаря не выполняются (или показывают подсказку подключить).

## Заявка на доступ зависла

- Проверьте `access_request_status` в `logs/users.json`.
- Админ должен быть в `ADMIN_TELEGRAM_IDS` и вызвать `/pending`.
- Повторный `/start` при уже `pending` не создаёт вторую заявку (anti-spam).

## Команда работает, но календарь пустой

Проверьте:

- календарь успешно подключён через Web App (`calendar_last_checked_at`);
- app password Mail.ru с доступом к календарю (не обычный пароль почты);
- `HIDE_ALL_DAY_EVENTS` / declined PARTSTAT не скрывают все события;
- `LOG_LEVEL=DEBUG` для деталей CalDAV в `logs/bot.log`.

## Web App не открывается

- `WEBAPP_BASE_URL` должен быть **HTTPS** и доступен с телефона пользователя.
- Reverse proxy должен проксировать на `WEBAPP_HOST:WEBAPP_PORT` (обычно `127.0.0.1:8080`).
- Прямой доступ к порту 8080 из интернета не требуется и не рекомендуется.

## Telegram token неверный

Перевыпустите токен у BotFather и перезапустите бота.

## Дайджест не приходит

Проверьте `/settings` и `logs/subscriptions.json` (`digest_enabled`, день, время,
timezone).

Проверьте `logs/users.json`: без `has_calendar` шедулер пропускает пользователя.

Если `last_digest_sent_date` уже сегодня, повторной отправки не будет.

Устаревшие ключи в `.env` (`DIGEST_TIME`, `DIGEST_WEEKDAYS_ONLY`) scheduler не читает.
Глобально для даты дайджеста остаётся только `DIGEST_MODE`.

## Дайджест пришел дважды

Не запускайте два процесса с одним `TELEGRAM_BOT_TOKEN`.

## Loading-сообщение не отредактировалось

Штатный fallback: бот отправит итог новым сообщением и запишет warning в лог.

## Погода не отображается

```env
WEATHER_ENABLED=true
WEATHER_LOCATION=...
```

При ошибке Open-Meteo календарный дайджест должен работать без погодного блока.

## Тесты не запускаются после переноса папки

Пересоздайте venv или:

```bash
PYTHONPATH=venv/lib/python3.9/site-packages python3 -m pytest
```

## compileall падает на `._*.py`

AppleDouble-файлы на внешнем macOS-томе. Исключите их:

```bash
find satellite tests -name '*.py' ! -name '._*' -print0 \
  | xargs -0 python -m py_compile
```

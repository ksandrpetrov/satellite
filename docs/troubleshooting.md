# Troubleshooting

## Бот не запускается

### Invalid .env (заглушки из примера)

При старте `run_bot` проверяет обязательные поля. Типичные сообщения:

```text
Invalid .env:
- TELEGRAM_BOT_TOKEN: укажите токен от @BotFather ...
- WEBAPP_BASE_URL: укажите публичный HTTPS URL ...
```

Замените значения из `.env.example` на реальные. После правки:

- **systemd:** `sudo systemctl restart satellite-bot.service`;
- **Docker:** `make deploy` или `docker compose up -d` в `/opt/satellite`.

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

**TELEGRAM_BOT_TOKEN** — полный токен от @BotFather (`123456789:AAH...`). Заглушки
`123456:your-bot-token` (и подстрока `your-bot-token`) дают `Invalid .env` при старте;
`replace-me` из `.env.example` — замените на реальный токен, иначе `getMe` вернёт 401.

**WEBAPP_BASE_URL** — реальный HTTPS, не `https://your-domain.example/connect` и не путь
к файлу (`satellite/web/static/connect.html`). Для production на VPS:
`https://cassinilab.ru/connect` (домен из `deploy/ansible/group_vars/all.yml`).

### Неверный ключ шифрования

`TOKEN_ENCRYPTION_KEY` должен быть валидным Fernet-ключом (32-byte urlsafe base64).
Сгенерировать заново — см. [configuration.md](configuration.md).

После смены ключа расшифровка старых записей в `logs/users.json` падает —
пользователям нужно переподключить календарь в Web App.

При старте в `logs/bot.log` строка `Persistence loaded: … key_fingerprint=…`
показывает отпечаток текущего ключа (sha256[0:8]). Если после деплоя fingerprint
сменился, а пользователи не переподключали календарь — вероятна смена
`TOKEN_ENCRYPTION_KEY`. Сообщение `CRITICAL Encryption self-check failed` —
хотя бы один approved-пользователь с credentials не расшифровывается текущим
ключом; восстановите старый `.env` из бэкапа или попросите переподключить календарь.
Снапшоты JSON до правок: `logs/backups/` (см. [operations.md](operations.md#runtime-state)).

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
- для `@vk.team` / Mailroom: email `имя@vk.team`, сервер `calendar.mail.ru`, токен с правом **Календарь**;
- при ошибке «Токен не подошёл» проверьте CalDAV без Telegram:

  **systemd** (`install-server.sh`, есть `venv/` и `scripts/`):

  ```bash
  cd /opt/satellite && source venv/bin/activate
  export CALDAV_LOGIN='ваш@vk.team'
  read -s CALDAV_APP_PASSWORD && export CALDAV_APP_PASSWORD
  # если на Mac был principal URL:
  # export CALDAV_URL='https://calendar.mail.ru/principals/vk.team/имя/'
  python scripts/diagnose_caldav.py
  ```

  **Docker** (`make deploy`): в `/opt/satellite` только `docker-compose.yml` и `.env` —
  `scripts/` в образ не попадает. Смотрите `docker compose logs satellite` и
  `docker compose exec satellite tail -f /app/logs/bot.log`; для скриптов — временный
  клон репозитория на сервере (`bash scripts/install.sh --dev` в отдельном каталоге)
  или диагностика с ноутбука с теми же `CALDAV_*`.

  Если скрипт падает на сервере, но на Mac работает — смотрите `logs/bot.log` (сеть/VPN/firewall). Если скрипт OK, а Web App нет — проверьте одобрение доступа в `logs/users.json` и что Web App открыт из бота.
- `HIDE_ALL_DAY_EVENTS` / declined PARTSTAT не скрывают все события;
- приглашения не появляются в `/invitations`: в ICS должен быть ваш `mailto:` с
  `PARTSTAT=NEEDS-ACTION` или `DELEGATED` (иногда Mail.ru отдаёт ATTENDEE только в GET — см.
  PARTSTAT refresh в `caldav_client.py`); бот смотрит до **60 дней вперёд** и **14 дней назад**
  (не более **12** пунктов); недавно завершённые без ответа остаются в списке. Очень старые
  неотвеченные не попадут. Ответ «Не удалось обновить» — `logs/bot.log`
  (`PARTSTAT_UPDATE_FAILED`).
  Диагностика без Telegram — [`scripts/diagnose_invitation.py`](../scripts/diagnose_invitation.py)
  (тот же lookback 14 д при фильтре `collect_pending_invitations`; на Docker-сервере —
  из клона с `venv`, см. CalDAV выше):

  ```bash
  cd /opt/satellite && source venv/bin/activate   # systemd; для Docker — каталог с install.sh
  python scripts/diagnose_invitation.py --user-id <telegram_id>
  python scripts/diagnose_invitation.py --user-id <id> --summary "Standup"
  # опционально реальный ACCEPTED в CalDAV:
  python scripts/diagnose_invitation.py --user-id <id> --summary "Standup" --accept
  ```

  Без `--user-id`: `CALDAV_LOGIN` + `CALDAV_APP_PASSWORD` (как у `diagnose_caldav.py`).
  Скрипт для CalDAV-запроса берёт окно шире, чем UI бота (90 дней вперёд), но pending
  отбирает с `lookback_days=14`, как `/invitations`.
- `LOG_LEVEL=DEBUG` для деталей CalDAV в `logs/bot.log`.

## Web App не открывается

- `WEBAPP_BASE_URL` должен быть **HTTPS** и доступен с телефона пользователя.
- Reverse proxy должен проксировать на `WEBAPP_HOST:WEBAPP_PORT` (обычно `127.0.0.1:8080`).
- Прямой доступ к порту 8080 из интернета не требуется и не рекомендуется.
- Быстрая проверка изнутри контейнера/хоста: `curl -sS http://127.0.0.1:8080/healthz` → `{"status":"ok"}`.

### Docker-стек (бот в контейнере, внешний nginx)

- В контейнере бота обязательно `WEBAPP_HOST=0.0.0.0` (не `127.0.0.1`).
- `WEBAPP_BASE_URL` должен совпадать с публичным URL: `https://<domain>/connect`.
- Контейнер слушает `127.0.0.1:<satellite_host_port>` на хосте (default `8080`).
- Healthcheck контейнера: `docker compose ps` → колонка `STATUS` должна показать `healthy`.
- Проверка с сервера: `curl -sS -o /dev/null -w '%{http_code}\n' https://<domain>/connect` (ожидается **200**, не 404/502).
- **404 Not Found (nginx)** — в конфиге сайта нет `location` для `/connect` и
  `/api/calendar/` на `127.0.0.1:<satellite_host_port>`; см.
  [`deploy/nginx/satellite-webapp.conf.example`](../deploy/nginx/satellite-webapp.conf.example),
  затем `sudo nginx -t && sudo systemctl reload nginx`.
- Сначала `curl http://127.0.0.1:8080/healthz` на сервере: если не 200, чините бота, не nginx.
- Логи бота: `docker compose -f /opt/satellite/docker-compose.yml logs -f satellite`.
- Логи nginx: `sudo journalctl -u nginx -f` (или `/var/log/nginx/error.log`).

### Локальный запуск через ngrok/Cloudflare Tunnel

- `make env && make docker-up` — поднимает один контейнер бота с пробросом порта 8080.
- Снаружи: `ngrok http 8080` (или `cloudflared tunnel`), полученный HTTPS-URL вписать
  как `WEBAPP_BASE_URL=https://<ngrok-domain>/connect` в `.env`, затем `make docker-down && make docker-up`.
- В BotFather → `Bot Settings → Menu Button` укажите тот же `WEBAPP_BASE_URL`.

### Web App: «Сессия Telegram недействительна» / `unauthorized`

Это **не** ошибка CalDAV. Сервер не принял подпись `initData` от Telegram.

**Частые причины:**

1. **Страница открыта в Safari/Chrome**, а не в WebView Telegram. Не открывайте закладку `https://cassinilab.ru/connect`. Нужна кнопка **«Подключить календарь»** в **чате с ботом** («⚙️ Настройки» → inline-хаб → Web App), не «открыть в браузере».
2. **Кнопка меню в BotFather** настроена как обычный URL, а не **Web App** — тогда Desktop открывает Safari без сессии. BotFather → бот → Menu Button → **Web App** → `https://cassinilab.ru/connect`.
3. **На сервере другой `TELEGRAM_BOT_TOKEN`**, чем бот, из которого открыли Web App (тестовый vs боевой бот).

Проверка на VPS:

```bash
TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' /opt/satellite/.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS "https://api.telegram.org/bot${TOKEN}/getMe"
```

`username` в ответе должен совпадать с ботом «Чайка», из которого вы жмёте кнопку. После смены токена: `sudo systemctl restart satellite-bot.service`.

Логи (подсказка по причине):

```bash
journalctl -u satellite-bot.service -n 50 | grep 'Reject WebApp'
```

- `Missing initData` — открыли не из Telegram.
- `Invalid initData signature` — неверный токен в `.env`.
- `initData expired` — закройте Web App и откройте снова.

В nginx **обязательно** проксируйте заголовок (иначе в логе `Missing initData`):

```nginx
proxy_set_header X-Telegram-Init-Data $http_x_telegram_init_data;
```

В `location`: `/connect` и `/api/calendar/`. Затем
`sudo nginx -t && sudo systemctl reload nginx`.

Начиная с актуальной версии кода, `initData` также передаётся в query (`?initData=...`) — работает даже если заголовок режется.

### Web App: `connect_token_invalid` / «Ссылка устарела»

Кнопки «Подключить календарь» в чате открывают `/connect/<token>`. Токен живёт
**15 минут** (`ConnectTokenStore`, `logs/connect-tokens.json`). Если Web App
открыт по старой ссылке или скопирован в браузер — API вернёт `connect_token_invalid`.

**Что делать:** снова «⚙️ Настройки» → «🔌 Подключить» (или `/connect`) и открыть
Web App из свежего сообщения бота. Menu Button без токена в URL по-прежнему
требует валидный `initData` от Telegram.

## Telegram token неверный (HTTP 401 Unauthorized)

Telegram отвечает 401 на `getUpdates` / `setMyCommands`, если `TELEGRAM_BOT_TOKEN`
в `.env` неверный, устарел или искажён при копировании.

На сервере:

```bash
# Формат строки (без кавычек и пробелов вокруг =)
sudo grep '^TELEGRAM_BOT_TOKEN=' /opt/satellite/.env | sed 's/\(.\{12\}\).*/\1…/'

# Проверка токена (должен быть "ok":true)
sudo -u satellite bash -c 'set -a; . /opt/satellite/.env; set +a; \
  curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getMe"'
```

Типичные ошибки:

- кавычки в `.env`: `TELEGRAM_BOT_TOKEN="123:ABC"` — systemd может передать
  кавычки как часть значения;
- пробел после `=` или в конце строки;
- вставлен @username бота вместо токена;
- токен отозван в @BotFather, а в `.env` остался старый.

Исправление: [@BotFather](https://t.me/BotFather) → ваш бот → **API Token** →
скопировать целиком (`цифры:буквы`), вписать в `/opt/satellite/.env`,
`sudo systemctl restart satellite-bot.service`.

После обновления кода бот при старте сам вызовет `getMe` и упадёт с понятным
текстом, если токен невалиден.

В Docker та же проверка: контейнер `satellite` перезапускается, если токен
неверен или нет исходящего доступа к `api.telegram.org` — смотрите
`docker compose logs satellite`.

## Дайджест не приходит

Проверьте `/settings` → «🔔 Дайджест» и `logs/subscriptions.json`
(`digest_enabled`, `digest_days`, `digest_time`, `digest_timezone`,
`telegram_user_id` должен совпадать с записью в `users.json`).

Проверьте `logs/users.json`: без `has_calendar` шедулер пропускает пользователя.
При нескольких календарях — что нужные URL включены в «📚 Календари»
(`enabled_calendar_urls`).

Если `last_digest_sent_date` уже сегодня, повторной отправки не будет.

Устаревшие ключи в `.env` (`DIGEST_TIME`, `DIGEST_WEEKDAYS_ONLY`) scheduler не читает.
Глобально для даты дайджеста остаётся только `DIGEST_MODE`.

## Дайджест пришел дважды

Не запускайте два процесса с одним `TELEGRAM_BOT_TOKEN`.

## Два PNG аналитики подряд / «Уже строю отчёт»

Недельная аналитика строится долго (CalDAV за ~13 недель). Повторное нажатие
«Построить отчёт» во время сборки или сразу после успешной отправки не запускает
второй прогон: пользователь видит toast «Уже строю отчёт — подожди немного».
Cooldown после успеха — 45 с (`ActionGuard` в `handlers/analytics.py`).

Если два PNG всё же пришли на старой версии бота — обновите деплой. В логе
ищите пары `Sent weekly analytics` с разницой в секундах для одного `chat_id`.

## Два плана или два списка upcoming подряд

Повтор `/today` (или кнопки плана) и `/upcoming`, пока первый запрос ещё идёт
или в течение cooldown после успеха, молча игнорируется (`ActionGuard` в
`plan.py` — 30 с, `calendar_list.py` — 15 с). В логе: `Plan run skipped
(duplicate within cooldown)` или `Upcoming skipped (duplicate within cooldown)`.

## Два списка приглашений или manage подряд

Повтор `/invitations` или `/manage` (и кнопки «📨 Приглашения» / «🛠 Изменить статус»),
пока первый CalDAV-запрос ещё идёт или в течение 10 с после успешного открытия,
молча игнорируется (`ActionGuard` в `calendar_invitations.py` /
`calendar_manage.py`). В логе: `Invitations open skipped` или `Manage open skipped`.

Ответ на встречу (PARTSTAT) и «Обновить» на том же экране — через
`edit_callback_message`, не второй streaming-open.

## Черновик не обновился / callback-edit не сработал

При streaming-open финал — `stream.finish`. Если Telegram не принял edit
callback-экрана, штатный fallback: бот отправит итог новым сообщением и запишет
warning в лог (`message_editing.py`).

Для аналитики зависший черновик «Чайка сводит неделю…» при падении сборки
(PIL, CalDAV, `sendPhoto`) должен заменяться на `ERR_GENERIC_HANDLER_TEXT` или
`ERR_CALDAV_UNAVAILABLE_TEXT` — см. `tests/test_analytics_handler.py`.

## Погода не отображается

```env
WEATHER_ENABLED=true
WEATHER_LOCATION=...
```

При ошибке Open-Meteo календарный дайджест должен работать без погодного блока.

## Автодеплой GitHub Actions и Docker на сервере

См. также [operations.md — автодеплой](operations.md#автодеплой-из-github-actions),
[deploy/README.md](../deploy/README.md).

### Job deploy не запустился после тега `v*`

Workflow [`deploy.yml`](../.github/workflows/deploy.yml) на теге `v*` собирает образ
с semver-тегом в GHCR, но job **deploy** на сервер **не** выполняется. Для выката на prod:
push в `main`, **Run workflow** на ветке `main`, или локально `ci-deploy-remote.sh`
с нужным `SATELLITE_IMAGE`.

### `Missing Actions secret: DEPLOY_HOST` (и др.)

В `Settings → Secrets and variables → Actions` должны быть заданы
`DEPLOY_HOST`, `DEPLOY_USER`, `SSH_PRIVATE_KEY`. Значения без лишних кавычек;
`DEPLOY_HOST` — только hostname или IP (`203.0.113.10`, `example.com`), без
`https://` и без пробелов/перевода строки в конце (скрипт обрезает CR/LF, но не
исправляет мусор внутри строки).

### SSH: `hostname contains invalid characters`

Секрет `DEPLOY_HOST` скопирован с хвостовым `\n` или с недопустимым символом.
Пересохраните секрет; локально проверьте:

```bash
DEPLOY_HOST="$(printf '%s' 'ваш-хост' | tr -d '\r\n')"
ssh -o BatchMode=yes "$DEPLOY_USER@$DEPLOY_HOST" true
```

### `docker-compose.yml not found in /opt/satellite`

Первичный стек ещё не накатан. С ноутбука один раз: `make deploy` (Ansible).
Rolling update из Actions только подтягивает образ и перезапускает сервис `satellite`.

### `docker compose pull` / `unauthorized` (GHCR)

Пакет в GHCR приватный — задайте секрет `GHCR_PULL_TOKEN` (PAT с `read:packages`)
или сделайте пакет **public** (`Settings → Packages → satellite`).

### `bind: address already in use` на `127.0.0.1:8080`

На том же порту слушает **systemd** `satellite-bot.service` (старая установка).
[`ci-deploy-remote.sh`](../scripts/ci-deploy-remote.sh) и Ansible playbook останавливают
и отключают unit перед `docker compose up`. Вручную:

```bash
sudo systemctl stop satellite-bot.service
sudo systemctl disable satellite-bot.service
cd /opt/satellite && docker compose up -d satellite
```

Не держите systemd и Docker с одним `TELEGRAM_BOT_TOKEN` одновременно.

### Push в `main`, но бот на сервере старый

Проверьте, что workflow `deploy` завершился зелёным, в `/opt/satellite/.env` актуальный
`SATELLITE_IMAGE=ghcr.io/...:sha-<short>`, контейнер пересоздан:
`docker compose ps satellite`, `docker compose logs --tail=50 satellite`.

## Тесты не запускаются после переноса папки

Пересоздайте venv или:

```bash
# подставьте версию Python из venv (в CI — 3.11)
PYTHONPATH=venv/lib/python3.11/site-packages python3 -m pytest
```

## compileall падает на `._*.py`

AppleDouble-файлы на внешнем macOS-томе. Исключите их:

```bash
find satellite tests -name '*.py' ! -name '._*' -print0 \
  | xargs -0 python -m py_compile
```

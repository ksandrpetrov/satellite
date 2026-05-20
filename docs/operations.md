# Эксплуатация и деплой

## Локальный запуск

```bash
cd /path/to/satellite
source venv/bin/activate
python telegram_test_command.py
```

Остановить: `Ctrl+C`.

## Запуск на сервере

Первичная установка на Linux-сервере (VPS, домашний сервер и т.п.):

```bash
# Зависимости ОС (Debian/Ubuntu)
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip

# Код и окружение
sudo mkdir -p /opt/satellite
sudo chown "$USER":"$USER" /opt/satellite
git clone <url-репозитория> /opt/satellite
cd /opt/satellite

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Отредактируйте .env: TELEGRAM_BOT_TOKEN, TOKEN_ENCRYPTION_KEY,
# ADMIN_TELEGRAM_IDS, WEBAPP_BASE_URL (см. docs/configuration.md)
mkdir -p logs
```

Проверка вручную перед systemd:

```bash
cd /opt/satellite
source venv/bin/activate
python telegram_test_command.py
```

В Telegram отправьте боту `/start`. Остановить тестовый запуск: `Ctrl+C`.

### systemd

Создайте unit-файл `/etc/systemd/system/satellite-bot.service`:

```ini
[Unit]
Description=Satellite Telegram calendar bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=satellite
Group=satellite
WorkingDirectory=/opt/satellite
ExecStart=/opt/satellite/venv/bin/python /opt/satellite/telegram_test_command.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

Замените `User`/`Group` и пути, если проект лежит не в `/opt/satellite`.
`.env` читается из `WorkingDirectory` — положите его рядом с `telegram_test_command.py`.

Включить и запустить:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now satellite-bot.service
sudo systemctl status satellite-bot.service
```

Остановить бота:

```bash
sudo systemctl stop satellite-bot.service
```

После изменения unit-файла:

```bash
sudo systemctl daemon-reload
sudo systemctl restart satellite-bot.service
```

Логи:

```bash
journalctl -u satellite-bot.service -f
tail -f /opt/satellite/logs/bot.log
```

После обновления кода остановите уже запущенного бота, обновите файлы и
запустите сервис снова. Так процесс перечитает новый код:

```bash
cd /opt/satellite
sudo systemctl stop satellite-bot.service
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl start satellite-bot.service
sudo systemctl status satellite-bot.service
```

Короткий вариант без явной остановки — `sudo systemctl restart satellite-bot.service`.

Если бот не стартует с ошибкой про lock — уже работает другой процесс с тем же
токеном. Найдите и остановите лишний: `pgrep -af telegram_test_command`.

## Production-процесс

Основной процесс — один long-polling экземпляр бота. Не запускайте два процесса
с одним `TELEGRAM_BOT_TOKEN`: они будут конкурировать за Telegram updates.

Защита от второго экземпляра:

```text
logs/bot.lock
```

Если lock занят, бот завершится с ошибкой и напишет причину в лог.

## Reverse proxy для Web App

Telegram открывает только публичный HTTPS URL из `WEBAPP_BASE_URL`. Типичная схема:

```text
Internet → nginx/Caddy (TLS) → 127.0.0.1:WEBAPP_PORT
```

Пример фрагмента nginx (замените домен и путь):

```nginx
location /connect {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

Проверьте, что страница открывается в браузере по тому же URL, что в `.env`.

## Runtime State

```text
logs/bot.log
logs/bot.lock
logs/telegram-offset.json
logs/subscriptions.json
logs/users.json
```

- `telegram-offset.json` — offset long-polling.
- `subscriptions.json` — настройки дайджеста.
- `users.json` — статусы доступа и зашифрованные CalDAV-credentials.
- `bot.log` — runtime-логи.

Эти файлы не коммитятся. Резервное копирование `users.json` и `.env`
(включая `TOKEN_ENCRYPTION_KEY`) обязательно при переносе сервера.

## Runtime State (legacy)

Ранее использовались `user-calendar-map.json` и глобальные Mail.ru-credentials
в `.env` — они удалены из конфигурации.

## Scheduler Lifecycle

Scheduler стартует вместе с `TelegramBot` и останавливается при shutdown.

Он не создает отдельные per-user jobs. Вместо этого один thread раз в 30 секунд
проверяет активных подписчиков. Это проще и устойчивее для небольшого числа
пользователей.

## Обновление

Рекомендуемый порядок:

```bash
cd /path/to/satellite
source venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
python telegram_test_command.py
```

На сервере для production достаточно `requirements.txt`; dev-зависимости нужны
только для локальной разработки и CI.

На production-сервере после обновления перезапустите сервис.

## Наблюдение

Что смотреть в логах:

- старт и остановка бота;
- ошибки Telegram API;
- ошибки CalDAV;
- ошибки погоды;
- scheduler summary `checked/due/sent/failed`;
- неизвестные callback;
- ошибки валидации времени.

Не должно быть:

- stack trace в сообщениях пользователю;
- токенов в логах TelegramError;
- частых логов каждую секунду без событий.

# Исходящие запросы Чайки через VPN-сервер

Бот, Web App, `users.json` и расписания остаются на российском сервере.
Отдельный контейнер `satellite-proxy` принимает HTTP CONNECT в сети Compose
и отправляет запросы через существующий VLESS REALITY + Vision на VPN-сервере.
Проверка HTTPS-сертификатов сохраняется. Публичный порт прокси не открывается.

Используется штатная поддержка `HTTP_PROXY` / `HTTPS_PROXY` в
[Requests](https://requests.readthedocs.io/en/latest/user/advanced/#proxies).
Через прокси идут Telegram и погода. `localhost`, `calendar.mail.ru` и
`caldav.yandex.ru` исключены через `NO_PROXY`: российские календари доступны
напрямую; Mail.ru через текущий VPN-сервер уходит в таймаут. Для другого CalDAV
endpoint сначала проверьте оба маршрута и при необходимости добавьте его имя
в `NO_PROXY`. Системные маршруты хоста и другие приложения не меняются.

## Подготовка

1. На российском сервере сохраните закрытую резервную копию `.env`,
   `docker-compose.yml` и существующего `docker-compose.override.yml`, если он есть.
   Не заменяйте существующий override целиком: объедините настройки.
2. В `/opt/satellite/proxy/xray` поместите проверенный Linux-бинарник Xray
   соответствующей архитектуры. Для текущего amd64 VPN проверена версия 26.9.30,
   SHA256 `96efb28b8b2086275598dc46e73b5dc340da948b4e1ccc4f1719f83f67b793a7`.
   Источник — `/usr/local/x-ui/bin/xray-linux-amd64` действующего VPN-сервера.
3. Возьмите экспортированный клиентский профиль VLESS с VPN-сервера
   (`/etc/vpn-stack/profiles/agent/reality-xray.json`) и сохраните **отдельную**
   копию как `/opt/satellite/proxy/config.json`. Сохраните адрес, UUID, ключ,
   SNI, short ID и flow. Для этой копии замените `inbounds` на:

   ```json
   [{
     "tag": "satellite-http",
     "listen": "0.0.0.0",
     "port": 3128,
     "protocol": "http",
     "settings": {"allowTransparent": false}
   }]
   ```

   Установите `log` в `{"loglevel":"warning","access":"none"}`,
   у VLESS outbound — `"mux":{"enabled":false}`. Убедитесь, что адрес в экспорте
   соответствует действующему VPN-серверу. Не сохраняйте UUID и конфиг в Git.
   [Документация HTTP inbound](https://xtls.github.io/en/config/inbounds/http.html).
4. Права: бинарник `root:root 0755`, конфиг `root:65534 0640`.
   Скопируйте [override](docker-compose.override.yml) в
   `/opt/satellite/docker-compose.override.yml`. Контейнер использует уже
   установленный `SATELLITE_IMAGE`; образ приложения пересобирать не нужно.
5. Если в старом Compose есть `extra_hosts: api.telegram.org:host-gateway`,
   после резервного копирования удалите именно эту подмену. HTTP-прокси сам
   передаёт имя Telegram VPN-серверу; локальный TLS-перенаправитель не нужен.

## Запуск и проверка

Из `/opt/satellite`, до переключения бота:

```bash
sha256sum proxy/xray
docker compose config --quiet
docker compose run --rm --no-deps satellite-proxy run -test -config /etc/xray/config.json
docker compose up -d satellite-proxy
docker compose ps
docker compose exec -T satellite-proxy curl --noproxy '' \
  --proxy http://127.0.0.1:3128 --fail --silent --show-error \
  --max-time 15 https://api.ipify.org
```

IP выхода должен совпасть с VPN-сервером, а `satellite-proxy` — стать `healthy`.
После этого `docker compose up -d satellite` пересоздаёт единственный экземпляр
бота с прежним образом и volume. Проверьте `getMe` без вывода токена,
успешный long-polling в журнале, отсутствие новых сетевых ошибок, CalDAV,
погоду и публичный `/healthz`. Сам `/healthz` не проверяет Telegram.

`restart: unless-stopped` восстанавливает оба контейнера после перезагрузки.
Повторный `docker compose up -d satellite`, включая CI-деплой, автоматически
читает override и запускает зависимость. Healthcheck проверяет HTTPS до Telegram
через VPN; при потере связи запросы не переключаются незаметно на прямой маршрут.
VPN-сервер должен быть доступен, чтобы новый запуск бота прошёл проверку зависимости.

## Откат

Сохраните текущие файлы перед откатом. Восстановите прежний override, если он
существовал. Если до настройки его не было — уберите только добавленный файл
`docker-compose.override.yml`. Выполните `docker compose up -d satellite`;
затем остановите и удалите только контейнер `satellite-proxy`.
Не используйте `down -v`: volume с пользовательскими данными нужен боту.
Проверьте отсутствие proxy-переменных у бота и его `/healthz`.

Если прямой доступ к Telegram по-прежнему недоступен, откат маршрута не восстановит
доставку сообщений. Приватные конфиги и резервные копии храните вне репозитория.

## Действующее развёртывание

Применено 8 октября 2026 года: бот на `178.217.99.88`, выход в Telegram и
Open-Meteo через `179.254.166.33:443`. Основной образ сохранён:
`ghcr.io/ksandrpetrov/satellite:sha-a2a24bc`. Mail.ru идёт напрямую.
Оба контейнера используют `restart: unless-stopped`; Docker включён в автозапуск.

Проверены `getMe`, IP выхода из контейнера бота, оба подключённых календаря,
почасовой прогноз и публичные Web App endpoints. После настройки scheduler
собрал и отправил дайджест за 8 октября. Прокси не публикует порты на хосте.

Снимок до изменения: `/var/backups/satellite-proxy/20261008T052542Z` на российском
сервере. Приватная локальная копия и профили находятся в
`~/.codex/private/satellite-proxy-20261008/`. Пароль SSH в этих файлах не хранится.

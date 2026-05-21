# Telegram UX

## Commands

Interactive-бот распознает:

```text
/start
/help
/pending          # только ADMIN_TELEGRAM_IDS
td
tm
dat
/td
/tm
/dat
/today
/tomorrow
/aftertomorrow
/after_tomorrow
/upcoming
/events           # алиас /upcoming
/invitations
/invites          # алиас /invitations
/respond          # алиас /invitations
/manage
/edit             # алиас /manage
/status           # алиас /manage
/create
/addevent         # алиас /create
/connect
/settings
/digest
/stopdigest
/calendars         # алиас /calendar_sources
/foreign           # алиас /shared_calendars, /foreign_calendars
```

В меню Telegram (`setMyCommands`) зарегистрированы: `start`, `today`, `tomorrow`,
`aftertomorrow`, `upcoming`, `invitations`, `create`, `settings`, `help`. Кнопку
«Меню» рядом с полем ввода (список команд, Web App «🔌 Календарь» и т.д.) задают
в BotFather — бот при старте её не меняет.
Короткие алиасы (`td`/`tm`/`dat`),
`/digest`/`/stopdigest`, `/calendars`, `/foreign` и `/connect` работают, но в
списке команд не показываются.

`/digest` включает подписку (как `/subscribe`), **не** открывает экран настроек.
`/stopdigest` отключает дайджест, запись в `subscriptions.json` сохраняется.
Основной интерфейс — кнопка «⚙️ Настройки» или `/settings` (inline-хаб).

## Access and calendar connection

1. **Первый контакт.** `/start` создаёт или обновляет запись в `logs/users.json`
   и при необходимости открывает заявку на доступ (`access_request_status=pending`).
   Пользователь видит инструкцию; админы получают уведомление (если заявка новая).

2. **Админ.** `/pending` показывает очередь заявок и кнопки одобрения/отклонения.
   Доступно только id из `ADMIN_TELEGRAM_IDS`.

3. **После одобрения.** Пользователь подключает календарь через кнопку
   «Подключить календарь» (Telegram Web App, `WEBAPP_BASE_URL`). В Web App
   выбирается провайдер (`mailru` — Mail.ru / Mailroom; `yandex` в UI пока
   «скоро»). Пароль приложения шифруется в `encrypted_credentials`; CalDAV URL —
   в `primary_calendar_url`.

4. **Команды плана, списка, создания событий и дайджест** работают только при
   `UserRecord.has_calendar` (approved + connected + непустые credentials).

5. **Настройки и календарь.** Кнопка «⚙️ Настройки» (`/settings`) открывает
   inline-хаб: дайджест, **📊 аналитика недели** (PNG + подпись), выбор календарей
   для плана, Web App connect, проверка и отключение (последние два — при
   `has_calendar`).

   **Аналитика:** «📊 Аналитика» → выбор рабочего дня (9:00–18:00 / 10:00–19:00) →
   «Построить отчёт». Потоковый ответ: черновик «Чайка сводит неделю…»
   (`send_message_draft` + `upload_photo`), затем PNG с подписью отдельным
   `sendPhoto` (в личке — message effect ✨). Повторный «Построить отчёт», пока
   идёт сборка или в течение 45 с после успешной отправки, не запускает второй
   отчёт — toast «Уже строю отчёт — подожди немного» (`ActionGuard` в
   `handlers/analytics.py`). Один запрос CalDAV (~13 недель), сравнение с прошлой
   неделей, тренд по кварталу. Системные события (🍕 обед, «день без встреч»,
   all-day) и неподтверждённые приглашения в метрики не входят.

`/start` и `/help` отвечают всем остальным пользователям без проверки календаря.
`/help` снимает старую reply-клавиатуру (`remove_keyboard`).

## Reply keyboard (approved)

После одобрения `/start` показывает компактную reply-клавиатуру
(`build_approved_main_keyboard`):

```text
📅 Сегодня          ➡️ Завтра
🗓 Ближайшие события 📨 Приглашения
🛠 Изменить статус  👥 Чужие календари
➕ Создать событие   ⚙️ Настройки
```

Подключение календаря, дайджест и «📚 Календари» (источники плана) — в inline-хабе
настроек, не на reply-клавиатуре.

Legacy-тексты старой клавиатуры тоже распознаются:

```text
➡️ Завтра
⏭ Послезавтра
⚙️ Настройки дайджеста
📚 Календари
🔔 Подписаться на дайджест
🔕 Отключить дайджест
🔕 Отписаться от дайджеста
🔌 Подключить календарь / 🔄 Переподключить
✅ Проверить подключение   🗑 Отключить календарь
```

## Upcoming events

`/upcoming` (или кнопка «🗓 Ближайшие события») показывает список событий на
7 дней вперёд (до 30 штук), сгруппированный по дням с текущего дня
(«Сегодня», «Завтра», далее «Пт, 22.05» и т.д.). Отменённые события скрываются.
Встречи внутри дня нумеруются так же, как в дайджесте: `1️⃣`…`🔟`, далее
`11.` и т.д. (`event_index_marker` в `calendar/events.py`). Сценарий:
`open_streaming_reply` → `UserCalendarService.list_events` → финальный список;
см. [Streaming delivery](#streaming-delivery). Повтор
`/upcoming` в cooldown — молча (`ActionGuard`, 15 с).

## Invitations (PARTSTAT)

`/invitations` (кнопка «📨 Приглашения», алиасы `/invites`, `/respond`) показывает
встречи, где у пользователя `PARTSTAT` = `NEEDS-ACTION` или `DELEGATED`, на горизонте
до 60 дней вперёд и до 14 дней назад (не более 12 пунктов). Уже принятые/отклонённые
скрываются; недавно завершённые, но без ответа, остаются в списке
(`collect_pending_invitations` в `calendar/events.py`).

Сценарий открытия — `open_streaming_reply` → статус «📨 Чайка собирает приглашения…»
→ `UserCalendarService.list_events_for_invitations` → `collect_pending_invitations`
→ `stream.finish` (список + inline-кнопки). Повтор `/invitations` в cooldown — молча
(`ActionGuard`, 10 с). См. [Streaming delivery](#streaming-delivery).

Под каждым событием — **Принять** / **Отклонить** / **Может быть**; ответ пишется
в CalDAV через `set_attendee_partstat` (Mail.ru — `CalDAVClient.update_attendee_partstat`).
Callback data: префикс `inv:` (`CB_INV_*` в [`messages_ru/_core.py`](../satellite/messages_ru/_core.py)).

Тот же экран открывается из хаба настроек → **📚 Календари** → **📨 Приглашения**
(`CB_SETTINGS_INVITATIONS`). «⬅️ В календарь» возвращает в подменю календаря хаба.

## Manage events (PARTSTAT)

`/manage` (кнопка «🛠 Изменить статус», алиасы `/edit`, `/status`) — список встреч
на 7 дней, где можно сменить свой `PARTSTAT` (не только NEEDS-ACTION). Открытие
списка — streaming (`MANAGE_FETCH_STATUS` → финал с кнопками); cooldown 10 с.
Детальный экран по встрече, те же CalDAV-операции, что в `/invitations`
(`set_attendee_partstat`). Callback data: префикс `mng:` (`CB_MANAGE_*`).

## Digest and analytics metrics

**Дайджест и аналитика:** неподтверждённые приглашения не входят в метрики
занятости; в расписании дня вместо номера встречи — `⚠️` (`is_pending` в
`seagull/render.py`). Ответить на приглашение можно из `/invitations` или в
клиенте календаря — после `ACCEPTED` встреча попадёт в план и метрики.

## Create event

`/create` (или кнопка «➕ Создать событие») запускает пошаговый FSM
(`calendar_state.py`):

1. название;
2. дата (`ДД.ММ.ГГГГ`, «сегодня», «завтра»);
3. время начала (`09:30`, `9:30`, `9 30` — см. [Time input](#time-input));
4. длительность в минутах;
5. подтверждение inline-кнопками (`create:confirm` / `create:cancel`).

Событие создаётся в primary-календаре пользователя через `UserCalendarService`.

## Settings hub

`/settings` (кнопка «⚙️ Настройки») открывает inline-хаб (`settings_hub.py`):

- **🔔 Дайджест** — экран настроек дайджеста (`settings.py`);
- **📊 Аналитика недели** — экран выбора рабочего дня и построения отчёта
  (`analytics.py`; навигация «Назад» — `CB_ANALYTICS_BACK` в хабе);
- **📚 Календари** — подменю: приглашения, выбор календарей для плана, connect,
  проверка и отключение (`calendar_sources.py` для списка URL; при одном календаре
  в плане — подсказка, без списка);
- **🔌 Подключить / 🔄 Переподключить** — Web App (`WEBAPP_BASE_URL`);
- **✅ Проверить** / **🗑 Отключить** — только при `has_calendar`.

Callback data хаба: `CB_SETTINGS_*` / `CB_ANALYTICS_*` в [`messages_ru/_core.py`](../satellite/messages_ru/_core.py). Экран дайджеста —
`CB_DIGEST_*`.

Каждый callback получает `answerCallbackQuery` best-effort. Неизвестный callback
логируется и безопасно игнорируется.

### Digest settings (из хаба)

- статус дайджеста;
- дни отправки (`weekdays` / `all_days`);
- время отправки;
- кнопка включения или отключения;
- «Назад» возвращает в хаб настроек.

## Calendar sources (план и дайджест)

Команды `/calendars`, `/calendar_sources` или кнопка «📚 Календари» в хабе
настроек открывают inline-список CalDAV-календарей аккаунта. Галочкой отмечены
включённые URL; переключение пишет `enabled_calendar_urls` в `logs/users.json`.

Если список пуст — в плане/дайджесте используется только `primary_calendar_url`
(см. `effective_enabled_calendar_urls` в `calendar/selection.py`). События
агрегируются из всех включённых календарей.

Общая загрузка списка — `calendar_view.fetch_calendars` (не импортировать
`_fetch_calendars` из `calendar_sources` в другие модули).

## Foreign (shared) calendars

«👥 Чужие календари» или `/foreign` (`/shared_calendars`, `/foreign_calendars`)
— просмотр календарей, пошаренных на аккаунт пользователя (все из discovery,
кроме `primary_calendar_url`). Сценарий:

1. inline-список календарей;
2. выбор дня (сегодня / завтра);
3. список встреч на день (только чтение, без записи в `enabled_calendar_urls`).

Не влияет на дайджест и `/today` — только отдельный просмотр.

## Time input

Время в настройках дайджеста и при создании события парсится через
`time_utils.normalize_hhmm_input` (мягкая валидация) и `parse_hhmm` (строгая,
для расчётов). Один набор правил — не дублировать парсинг в хендлерах.

Допустимые формы:

- разделитель — двоеточие или пробел: `9:30`, `09:30`, `9 30`, `18 25`;
- минуты — ровно две цифры;
- часы — `0`…`23`;
- после успеха сохраняется канонический `HH:MM` (`09:30`).

Невалидно: `утром`, `900`, `09-00`, `25:00`, `12:99`.

### Digest time state

После кнопки `🕘 Время отправки` следующий обычный текст пользователя считается
новым временем, если он не похож на команду.

- невалидное время не сохраняется;
- state очищается после успешного ввода;
- state очищается кнопками `Назад` и `Закрыть`;
- команды и кнопки клавиатуры выходят из state.

FSM создания события (`calendar_state`) не пересекается с digest time state.

## Streaming delivery

План дня (`/today`, `/tomorrow`, …), `/upcoming`, `/invitations`, `/manage` и
недельная аналитика используют `streaming_delivery.open_streaming_reply`: черновик
через draft API (`sendMessageDraft` + промежуточные `push`), финал — `finish`
(текст + inline-клавиатура) или отдельный `sendPhoto` (аналитика). При ошибке
CalDAV/сборки черновик заменяется безопасным текстом (`ERR_*` из `messages_ru`).

Повтор команды или кнопки открытия, пока первый запрос ещё идёт или сразу после
успеха, блокируется `ActionGuard` в
[`action_guard.py`](../satellite/telegram_bot/handlers/action_guard.py)
(cooldown'ы — в [architecture.md](architecture.md)). План, upcoming, invitations и
manage — молча; аналитика — toast «Уже строю отчёт…».

**Callback refresh** (обновить список, ответ PARTSTAT, «Назад» в manage): тот же
экран через `edit_callback_message` (`message_editing.py`). Если edit не удался,
`edit_or_send_message` отправляет новое сообщение и пишет warning в лог.

## Authorization (кратко)

| Сценарий | Условие |
|----------|---------|
| `/start`, `/help` | всем |
| `/pending` | `ADMIN_TELEGRAM_IDS` |
| `/connect` | `approved` |
| План, upcoming, invitations, manage, create, чужие календари, настройки, подписка | `approved` + `has_calendar` |
| Выбор календарей для плана (из хаба) | `approved` + `has_calendar` |
| Check/disconnect (из хаба) | `approved` + `has_calendar` |
| Web App connect | `approved` (до первого успешного connect) |

Подробнее о полях store: [configuration.md](configuration.md#пользователи-и-доступ-logsusersjson).

## Web App (подключение календаря)

- Открывать **только из чата с ботом** (кнопка «🔌 Подключить календарь» в сообщениях
  бота или Menu Button типа **Web App**, если включён в BotFather), не закладкой в Safari/Chrome.
- URL в BotFather и в `.env` (`WEBAPP_BASE_URL`) должны совпадать, например
  `https://cassinilab.ru/connect`.
- В форме: email (полный `@vk.team` для Mailroom), app password с правом «Календарь»,
  CalDAV URL — пусто или principal URL с Mac.
- Ошибки: «Токен не подошёл» — CalDAV; «Сессия Telegram…» / `unauthorized` — initData
  (не из бота, другой токен в `.env`, nginx без прокси API). См.
  [troubleshooting.md](troubleshooting.md).

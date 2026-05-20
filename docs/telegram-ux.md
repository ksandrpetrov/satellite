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
`aftertomorrow`, `upcoming`, `create`, `connect`, `settings`, `help`. Короткие
алиасы (`td`/`tm`/`dat`), `/digest`/`/stopdigest`, `/calendars` и `/foreign`
работают, но в меню не показываются.

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
   «Построить отчёт». Один запрос CalDAV (~13 недель), сравнение с прошлой неделей,
   тренд по кварталу. Системные события (🍕 обед, «день без встреч», all-day) и
   неподтверждённые приглашения в метрики не входят.

`/start` и `/help` отвечают всем остальным пользователям без проверки календаря.
`/help` снимает старую reply-клавиатуру (`remove_keyboard`).

## Reply keyboard (approved)

После одобрения `/start` показывает компактную reply-клавиатуру
(`build_approved_main_keyboard`):

```text
📅 Сегодня          🗓 Ближайшие события
👥 Чужие календари
➕ Создать событие
⚙️ Настройки
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
loading message → `UserCalendarService.list_events` → edit.

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
- **📚 Календари** — какие CalDAV-календари учитывать в плане и автодайджесте
  (`calendar_sources.py`; при одном календаре — подсказка, без списка);
- **🔌 Подключить / 🔄 Переподключить** — Web App (`WEBAPP_BASE_URL`);
- **✅ Проверить** / **🗑 Отключить** — только при `has_calendar`.

Callback data хаба: `CB_SETTINGS_*` в `messages_ru.py`. Экран дайджеста —
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

## Loading Message

Для плана дня и списка upcoming используется сценарий:

```text
sendMessage("Чайка ищет встречи..." / "Чайка собирает ближайшие события…")
build digest / list events
editMessageText(final text)
```

Если edit не удался, `edit_or_send_message` отправляет новое сообщение и пишет
warning в лог.

Если построение дайджеста упало, loading-сообщение заменяется безопасным текстом
ошибки.

## Typing Action

`run_with_typing_action`:

- отправляет `typing` сразу;
- повторяет `typing` для долгих операций;
- не прерывает основной сценарий, если `sendChatAction` упал;
- останавливает background thread после завершения операции;
- по умолчанию досыпает остаток `TYPING_DISPLAY_SECONDS` (≈5 с) после `fn`.

Полагаться на то, что `sendMessage`/`editMessageText` сами сбрасывают typing,
нельзя: клиенты держат индикатор до 5 секунд после последнего `sendChatAction`.
Ожидание включено в интерактивных командах и в дайджесте планировщика.
`wait_for_typing_to_clear=False` — opt-out, когда задержка критичнее индикатора.

## Authorization (кратко)

| Сценарий | Условие |
|----------|---------|
| `/start`, `/help` | всем |
| `/pending` | `ADMIN_TELEGRAM_IDS` |
| `/connect` | `approved` |
| План, upcoming, create, чужие календари, настройки, подписка | `approved` + `has_calendar` |
| Выбор календарей для плана (из хаба) | `approved` + `has_calendar` |
| Check/disconnect (из хаба) | `approved` + `has_calendar` |
| Web App connect | `approved` (до первого успешного connect) |

Подробнее о полях store: [configuration.md](configuration.md#пользователи-и-доступ-logsusersjson).

## Web App (подключение календаря)

- Открывать **только из чата с ботом** (кнопка «🔌 Подключить календарь» или Menu Button
  типа **Web App** в BotFather), не закладкой в Safari/Chrome.
- URL в BotFather и в `.env` (`WEBAPP_BASE_URL`) должны совпадать, например
  `https://cassinilab.ru/connect`.
- В форме: email (полный `@vk.team` для Mailroom), app password с правом «Календарь»,
  CalDAV URL — пусто или principal URL с Mac.
- Ошибки: «Токен не подошёл» — CalDAV; «Сессия Telegram…» / `unauthorized` — initData
  (не из бота, другой токен в `.env`, nginx без прокси API). См.
  [troubleshooting.md](troubleshooting.md).

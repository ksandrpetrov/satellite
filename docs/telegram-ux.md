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
```

В меню Telegram (`setMyCommands`) зарегистрированы: `start`, `today`, `tomorrow`,
`aftertomorrow`, `upcoming`, `create`, `connect`, `settings`, `help`. Короткие
алиасы (`td`/`tm`/`dat`) и `/digest`/`/stopdigest` работают, но в меню не
показываются.

`/digest` и `/stopdigest` оставлены как текстовые команды совместимости.
Основной интерфейс настройки подписки — `/settings`.

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

5. **Проверка и отключение.** Кнопки «✅ Проверить подключение» и
   «🗑 Отключить календарь» доступны после успешного connect.

`/start` и `/help` отвечают всем остальным пользователям без проверки календаря.
`/help` снимает старую reply-клавиатуру (`remove_keyboard`).

## Reply keyboard (approved)

После одобрения `/start` показывает постоянную reply-клавиатуру:

```text
📅 Сегодня          🗓 Ближайшие события
➕ Создать событие
⚙️ Настройки дайджеста
🔌 Подключить календарь   (Web App; после connect — «🔄 Переподключить»)
✅ Проверить подключение   🗑 Отключить календарь   (только при has_calendar)
```

Legacy-тексты старой клавиатуры тоже распознаются:

```text
➡️ Завтра
⏭ Послезавтра
🔔 Подписаться на дайджест
🔕 Отключить дайджест
🔕 Отписаться от дайджеста
```

## Upcoming events

`/upcoming` (или кнопка «🗓 Ближайшие события») показывает список событий на
7 дней вперёд (до 30 штук). Отменённые события скрываются. Сценарий:
loading message → `UserCalendarService.list_events` → edit.

## Create event

`/create` (или кнопка «➕ Создать событие») запускает пошаговый FSM
(`calendar_state.py`):

1. название;
2. дата (`ДД.ММ.ГГГГ`, «сегодня», «завтра»);
3. время (`ЧЧ:ММ`);
4. длительность в минутах;
5. подтверждение inline-кнопками (`create:confirm` / `create:cancel`).

Событие создаётся в primary-календаре пользователя через `UserCalendarService`.

## Settings Screen

`/settings` открывает inline-экран:

- статус дайджеста;
- дни отправки;
- время отправки;
- кнопка включения или отключения.

Callback data лежат в `satellite/messages_ru.py` как константы `CB_DIGEST_*`.

Каждый callback получает `answerCallbackQuery` best-effort. Неизвестный callback
логируется и безопасно игнорируется.

## Time Input State (digest)

После кнопки `🕘 Время отправки` следующий обычный текст пользователя считается
новым временем, если он не похож на команду.

Правила:

- `8:30` нормализуется в `08:30`;
- `09:00` остается `09:00`;
- минуты должны быть двумя цифрами;
- невалидное время не сохраняется;
- state очищается после успешного ввода;
- state очищается кнопками `Назад` и `Закрыть`;
- пользователь не застревает, потому что команды и кнопки выходят из state.

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
| `/connect`, check/disconnect | `approved` |
| План, upcoming, create, настройки, подписка | `approved` + `has_calendar` |
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

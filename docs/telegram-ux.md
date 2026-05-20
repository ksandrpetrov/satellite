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
/settings
/digest
/stopdigest
```

`/digest` и `/stopdigest` оставлены как текстовые команды совместимости.
Основной интерфейс настройки подписки — `/settings`.

## Access and calendar connection

1. **Первый контакт.** `/start` создаёт или обновляет запись в `logs/users.json`
   и при необходимости открывает заявку на доступ (`access_request_status=pending`).
   Пользователь видит инструкцию; админы получают уведомление (если заявка новая).

2. **Админ.** `/pending` показывает очередь заявок и кнопки одобрения/отклонения.
   Доступно только id из `ADMIN_TELEGRAM_IDS`.

3. **После одобрения.** Пользователь подключает Mail.ru Calendar через кнопку
   Telegram Web App (`WEBAPP_BASE_URL`). Пароль приложения шифруется и сохраняется
   в `encrypted_credentials`; CalDAV URL — в `primary_calendar_url`.

4. **Команды плана и дайджест** работают только при `UserRecord.has_calendar`
   (approved + connected + непустые credentials).

`/start` и `/help` отвечают всем остальным пользователям без проверки календаря.

## Buttons

Старые reply-кнопки распознаются, даже если бот больше не отправляет новую
постоянную reply-клавиатуру:

```text
📅 Сегодня
➡️ Завтра
⏭ Послезавтра
🔔 Подписаться на дайджест
🔕 Отключить дайджест
⚙️ Настройки дайджеста
```

Legacy-текст `🔕 Отписаться от дайджеста` тоже распознается.

## Settings Screen

`/settings` открывает inline-экран:

- статус дайджеста;
- дни отправки;
- время отправки;
- кнопка включения или отключения.

Callback data лежат в `satellite/messages_ru.py` как константы `CB_DIGEST_*`.

Каждый callback получает `answerCallbackQuery` best-effort. Неизвестный callback
логируется и безопасно игнорируется.

## Time Input State

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

## Loading Message

Для плана дня используется сценарий:

```text
sendMessage("Чайка ищет встречи...")
build digest
editMessageText(final digest)
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
| План, настройки, подписка | `approved` + `has_calendar` |
| Web App connect | `approved` (до первого успешного connect) |

Подробнее о полях store: [configuration.md](configuration.md#пользователи-и-доступ-logsusersjson).

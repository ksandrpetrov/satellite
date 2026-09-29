# Аудит календаря и зависимостей — 29 сентября 2026

Проверены подключение через Web App, общий пользовательский календарный сервис,
Mail.ru CalDAV, получение событий, ответы на приглашения, кэши экранов и
параллельные операции Telegram / Web App / scheduler. Исправления проверяются
локально, с временными хранилищами и HTTP-стендами; production не изменялся.
Исходный полный pytest: **1369 passed**.

## Найденные дефекты и исправления

| Приоритет | Проблема и воспроизведение | Исправление и проверка |
|---|---|---|
| P1 | Задержать validate первого connect, выполнить второй connect или disconnect, отпустить первый: старые credentials записывались последними. | Счётчик намерений на пользователя, проверка перед commit; `test_late_connect_cannot_overwrite_newer_intent`, браузерный `test_disconnect_in_second_window_cancels_pending_connect`. |
| P1 | Проверка или чтение старого аккаунта завершаются после переподключения: старый статус мог менять новую запись, старые события считались текущими. | Идентификатор подключения из SHA-256 зашифрованного blob, проверка актуальности результата; `test_old_read_cannot_report_success_after_reconnect`. |
| P1 | Старые кнопки идентифицировали ресурс только по URL: после смены аккаунта могли использовать новые credentials. | Токен включает идентификатор подключения; `CalendarEventRef.connection_id` проверяется перед записью. Старый результат не переигрывается в новой сессии; тесты `test_old_event_reference_cannot_write_to_reconnected_account`, `test_event_tokens_are_bound_to_connection_and_fit_telegram_limit`, `test_receipt_from_previous_connection_is_not_replayed`. |
| P1 | Новый запрос с тем же логином и другим паролем закрывал клиент, ещё используемый другим запросом. | Операции одного календарного аккаунта сериализованы, проверка credentials использует отдельный клиент. `test_parallel_accounts_never_close_a_client_during_use`, `test_validation_does_not_replace_active_client_or_reuse_cached_auth`. |
| P1 | Изменить ответ в другом клиенте после первого GET: повторный экран мог бесконечно брать старый PARTSTAT из кэша. | Кэш ограничен одним проходом обогащения. `test_new_refresh_observes_response_changed_in_another_client`. Этот тест воспроизвёл старое поведение до исправления. |
| P1 | GET, оставшийся после дедлайна, мог записать старые данные после очистки кэша ответом на встречу. | Версия кэша меняется при новом проходе и записи; поздний GET не публикуется в новую версию. `test_late_get_cannot_repopulate_invalidated_partstat_cache`. |
| P1 | REPORT успешен, но GET для уточнения ATTENDEE/PARTSTAT не удался: приглашение могло исчезнуть без сообщения о неполноте. | Непроверенные кандидаты отмечаются; provider приглашений возвращает безопасную ошибку вместо успешного неполного списка. Scheduler не получает ложное успешное пустое состояние. `test_unavailable_attendee_get_marks_incomplete_invitation_read`, `test_provider_rejects_incomplete_invitation_read`. |
| P1 | Ответить на встречу, затем закончить более раннюю загрузку экрана: старый снимок мог восстановить приглашение. | Ревизии чтения и обновлений в EventTokenCache; устаревшая регистрация отклоняется. `test_delayed_screen_cannot_restore_invitation_after_answer`, `test_older_fetch_cannot_replace_newer_screen`. |
| P1 | По прежнему URL сервер вернул другой UID: запись проверяла ATTENDEE, но не выбранную встречу. | UID проверяется перед PUT и при повторном чтении после HEAD. `test_reused_event_url_cannot_answer_a_different_uid`. |
| P2 | Пользовательский CalDAV endpoint жил только в кэше и терялся после рестарта. | Необязательное поле `caldav_url` внутри зашифрованного payload; чтение старых payload сохранено. `test_custom_endpoint_survives_vault_roundtrip`, `test_persisted_endpoint_used_by_fresh_provider_after_restart`, `test_legacy_encrypted_credentials_remain_readable`. |
| P2 | Неудачный health-check сохранял `invalid`, после чего `require_connection` запрещал повторную проверку. | Отрицательная проба возвращает свой результат, но не удаляет возможность повторной проверки сохранённых credentials. `test_failed_probe_does_not_disable_future_recovery`. |
| P2 | Параллельные GET делили requests.Session, а завершение дедлайна не означало завершения сетевых потоков. | Пул с эксклюзивной выдачей Session на запрос; close дожидается активных HTTP-запросов. `test_parallel_http_requests_use_exclusive_sessions_and_close_after_release`. |

Дополнительно запись и отключение сериализованы на уровне пользователя:
начатая запись заканчивается до отключения, другие пользователи не блокируются
(`test_disconnect_waits_for_started_write_without_blocking_other_users`).
Login для фильтрации приглашений и аналитики берётся из того же результата,
что и события. Discovery больше не пишет полный URL с логином или сырое
исключение сервера в диагностическую строку.

P1 — неправильная запись/результат или потеря актуального состояния; P2 —
восстановление подключения и управление сетевыми ресурсами.

## Проверенные существующие контракты

- Авторизация initData/connect-token и approved-пользователь проверяются до Web API;
  секреты сохраняются через Fernet, JSON-store остаётся транзакционным.
- Выбранные/общие календари, строгий REPORT, частичные отказы и нормализация ICS:
  `test_caldav_range_failures`, `test_product_correctness`, `test_ical_parser`.
- Повторения, исключения серий, отмены, часовые пояса, DST, границы периода и
  идентичность участника: существующие тесты calendar/events и
  `test_invitation_series`, `test_attendee_identity`.
- Ответы ACCEPTED/TENTATIVE/DECLINED, условный PUT по ETag, конфликт 412,
  потерянный ответ записи, повторное чтение, частично сохранённая серия и
  отсутствие лишнего PUT: реальные HTTP-тесты `test_partstat_confirmation`
  и `test_product_correctness`.
- Дедуп повторных нажатий, противоположные решения, массовое принятие и
  восстановление результата после ошибки Telegram: `test_partstat_flow`,
  `test_partstat_results`, `test_invitation_accept_all`.
- Успешный пустой pending и ошибка загрузки различаются в scheduler;
  существующие проверки scheduler включены в полный pytest.

Повторный прогон существующих тестов здесь отделён от новых воспроизведений;
он не выдаётся за новый ручной аудит каждой ветки приложения.

## Обновление зависимостей

Версии проверены по PyPI JSON API. Прямые пины обновлены только в
`requirements.in` / `requirements-dev.in`; оба lock-файла пересобраны
`make lock` через **uv 0.11.32**. Транзитивные зависимости обновлены резолвером: всего изменились версии 30 пакетов (8 прямых и 22 транзитивных).
Ruff в `.pre-commit-config.yaml` синхронизирован с dev-пином.

| Пакет | Было | Стало |
|---|---|---|
| caldav | 3.2.1 | 3.3.1 |
| cryptography | 49.0.0 | 50.0.1 |
| icalendar | 7.2.2 | 7.3.0 |
| python-dotenv | 1.2.2 | 1.2.3 |
| coverage | 7.15.2 | 7.16.2 |
| ruff | 0.16.0 | 0.16.9 |
| mypy | 2.3.0 | 2.3.1 |
| pre-commit | 4.6.1 | 4.6.2 |

requests 2.34.2, Pillow 12.3.0, pytest 9.1.1 и Playwright 1.63.0 уже были
актуальными стабильными версиями. uv сознательно оставлен 0.11.32 по
согласованному ограничению, хотя доступен 0.12.20. Baseline Python 3.11 сохранён.

Проверены официальные примечания [CalDAV 3.3.1](https://github.com/python-caldav/caldav/releases/tag/v3.3.1),
[cryptography](https://cryptography.io/en/stable/changelog/) и
[icalendar](https://icalendar.readthedocs.io/en/stable/reference/changelog.html).
Поведение используемых API проверяется импортами, типами и HTTP round-trip тестами;
Fernet проверяется также на старом формате credentials. CalDAV использует
Niquests, для которого [заявлена потокобезопасность сессий](https://niquests.readthedocs.io/en/latest/user/advanced.html#thread-safety);
собственные PARTSTAT-запросы через requests дополнительно изолированы пулом сессий.

## Совместимость и ограничения

- HTTP-маршруты сохранены; конфликт подключения возвращает 409 и
  `CALENDAR_CONNECTION_CHANGED` с русским сообщением.
- Внутренний Event получает `_calendar_connection_id` и `_calendar_login`;
  публичный сериализатор Web API их не раскрывает. Тест точного словаря
  аналитического fetch обновлён под этот намеренный внутренний контракт.
- Тест конкурентного кэша переключён на новый helper `event_token`, сохранив
  блокировки и assertions. Проверки прямых пинов обновлены под выбранные версии.
- После обновления старые Telegram-кнопки без версии подключения потребуется
  обновить через список встреч. Формат callback остаётся в пределах 64 байт.
- Новые блокировки действуют в одном процессе; проект по-прежнему использует
  один экземпляр production-бота. Многопроцессный режим требует другой модели
  хранения/координации и не включён в эту работу.
- Синхронизация одного календарного аккаунта может увеличить ожидание ответа,
  когда по нему уже идёт тяжёлый REPORT. Разные аккаунты продолжают работать
  параллельно; внутри одного REPORT параллельные GET сохранены.
- Лимиты и горизонт дополнительной проверки PARTSTAT сохранены. Непроверенные
  кандидаты в приглашениях вызывают ошибку, которую можно повторить;
  аналитика сохраняет существующий best-effort контракт обогащения.
- Уже отправленный удалённый PUT нельзя отменить отключением. Отключение
  дожидается начатой записи; потеря ответа проверяется чтением, а неподтверждённый
  результат не объявляется успешным.
- Это проверка кода и локальных стендов, не доказательство отсутствия любых
  гонок у внешнего CalDAV/Telegram. Живые встречи пользователей не изменялись.
- Docker smoke не выполнен: Docker daemon недоступен. Пользовательская правка
  `deploy/ansible/inventory.yml` сохранена, деплой не выполнялся.

## Итоговые проверки

| Проверка | Результат |
|---|---|
| `make check`, Python 3.12.13 | **1393 passed**, 58.42 с; lock-check, lint, format-check, mypy и py_compile прошли |
| `make check VENV=/tmp/satellite-calendar-audit-py311`, Python 3.11.15 | **1393 passed**, 58.52 с; все проверки прошли |
| `make browser-test`, Python 3.12 | **72 passed**: 36 Chromium + 36 WebKit |
| `make browser-test`, Python 3.11 | **72 passed**: 36 Chromium + 36 WebKit |
| `uv pip check`, Python 3.11 и 3.12 | Установленные зависимости совместимы |
| `git diff --check` | Прошёл |
| Docker smoke | Не выполнен: daemon недоступен |

Добавлено 24 тестовых случая pytest и по одному браузерному сценарию в каждом
движке (Chromium и WebKit). Логи сохранены в `test-results/calendar-audit-2026-09-29/`.

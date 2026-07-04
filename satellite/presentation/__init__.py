"""Transport-agnostic формирование текста для Telegram.

Пакет намеренно без re-export'ов — импортируйте конкретный модуль:

- ``presentation.html`` — legacy HTML (`<blockquote>`, ``<tg-emoji>``, copy-кнопки);
- ``presentation.rich`` — Rich Message HTML (Bot API 10.1);
- ``presentation.calendar_lists`` — rich-списки /upcoming, /invitations, /manage;
- ``presentation.delivery`` — deliver/edit rich с fallback на legacy HTML
  (единственный модуль пакета, которому разрешён импорт ``telegram_bot.api``).
"""

"""User-facing strings — имя бота, welcome/help, подсказка клавиатуры."""

from __future__ import annotations

BOT_INPUT_PLACEHOLDER = "Куда летим? Жми кнопку или напиши команду"

BOT_NAME_RU = "Чайка 🪶"
BOT_SHORT_DESCRIPTION_RU = (
    "Сводка дня из календаря: план, дайджест, приглашения и аналитика недели."
)
BOT_DESCRIPTION_RU = (
    "Чайка подключается к Mail.ru или Яндекс Календарю и приносит:\n"
    "• план на сегодня, завтра и послезавтра;\n"
    "• утренний дайджест по расписанию;\n"
    "• ближайшие события, приглашения и смену статуса встреч;\n"
    "• недельную аналитику с графиком.\n\n"
    "Команды — в меню рядом с полем ввода. Настройки — /settings."
)


def _build_bot_welcome_html() -> str:
    from ..telegram_bot.html_format import blockquote, replace_first_char_with_tg_emoji

    tip = blockquote(
        "Подсказка: добавь в встречу эмоджи 🍕 и слово «обед» — чайка засчитает её "
        "обедом и подскажет окно."
    )
    head = replace_first_char_with_tg_emoji("🪶 С возвращением. Чайка на связи.\n\n", "🪶")
    return (
        f"{head}"
        "Нижние кнопки — это твой штурвал:\n"
        "📅 <b>Сегодня</b> / ➡️ <b>Завтра</b> — план на день\n"
        "🗓 <b>Ближайшие</b> — события на неделю вперёд\n"
        "📨 <b>Приглашения</b> — встречи, где нужно принять решение\n"
        "🛠 <b>Изменить статус</b> — поменять решение по любой ближайшей встрече\n"
        "👥 <b>Чужие календари</b> — что у коллег\n"
        "➕ <b>Создать</b> — новая встреча в твой календарь\n"
        "⚙️ <b>Настройки</b> — дайджест, аналитика, подключение\n\n"
        f"{tip}"
    )


def _build_bot_help_html() -> str:
    from ..telegram_bot.html_format import expandable_blockquote, replace_first_char_with_tg_emoji

    commands_block = expandable_blockquote(
        "/today, /tomorrow, /aftertomorrow — план дня\n"
        "/upcoming — ближайшие события\n"
        "/invitations — ответить на приглашения\n"
        "/manage — изменить статус встречи на неделе\n"
        "/foreign — чужие календари\n"
        "/create — создать встречу\n"
        "/settings — настройки\n"
        "/digest, /stopdigest — включить или выключить утренний дайджест",
        threshold=2,
    )
    head = replace_first_char_with_tg_emoji("🪶 <b>Как летать с Чайкой</b>\n\n", "🪶")
    return (
        f"{head}"
        "Чайка собирает встречи из твоего календаря и приносит сводку дня.\n\n"
        "<b>Кнопки внизу:</b>\n"
        "📅 Сегодня, ➡️ Завтра — план на день\n"
        "🗓 Ближайшие — события на 7 дней\n"
        "📨 Приглашения — принять, отклонить или «может быть»\n"
        "🛠 Изменить статус — поменять решение по любой встрече на неделе\n"
        "👥 Чужие календари — пошаренные от коллег\n"
        "➕ Создать событие — добавить встречу\n"
        "⚙️ Настройки — дайджест, аналитика, подключение\n\n"
        "<b>Команды:</b>\n"
        f"{commands_block}\n\n"
        "<i>Короткие алиасы: <code>td</code>, <code>tm</code>, <code>dat</code>.</i>"
    )


BOT_WELCOME_HTML = _build_bot_welcome_html()
BOT_HELP_HTML = _build_bot_help_html()

# Markup, который вычищает старую нижнюю Reply-клавиатуру у пользователей, у
# которых она ещё висит после миграции на меню команд Telegram. Передаётся
# в ``reply_markup`` обычных сообщений (например, на /start и /help).
REPLY_KEYBOARD_REMOVE: dict = {"remove_keyboard": True}


BOT_KEYBOARD_HINT = (
    "🪶 Чайка не узнала команду.\nЖми кнопку внизу или открой меню — там все основные действия."
)

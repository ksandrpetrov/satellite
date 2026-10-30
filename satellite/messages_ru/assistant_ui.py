"""Календарный помощник: интерфейс и проверенные подтверждения действий."""

from datetime import datetime, timedelta

from ..digest_utils import WEEKDAY_SHORT_RU

AI_HELP = (
    "## 🪶 Помощник по календарю\n"
    "Напиши обычным сообщением, что нужно сделать.\n\n"
    "## Посмотреть расписание\n\n"
    "• Как выглядит мой день или следующая неделя?\n"
    "• Когда завтра найдётся час без встреч?\n"
    "• Найди встречи с командой на следующей неделе.\n\n"
    "## Создать или перенести встречу\n\n"
    "• Создай «Подготовка отчёта» завтра с 15:00 до 16:00.\n"
    "• Перенеси завтрашнюю подготовку отчёта на час позже.\n\n"
    "## 💡 Улучшить расписание\n"
    "Нажми «Советы по календарю» или отправь /optimize. "
    "Покажу варианты и пользу каждого. Применю только по твоей просьбе.\n\n"
    "## Как я работаю\n"
    "Однозначную просьбу создать или перенести встречу выполняю сразу. "
    "Если не хватает деталей, есть совпадения или пересечения — уточню. "
    "В повторяющейся встрече меняю только выбранную дату.\n\n"
    "## Данные и история\n"
    "Передаю в OpenAI текст запроса, названия и время нужных событий. "
    "Контекст храню зашифрованным до 24 часов после последнего сообщения.\n"
    "Начать новый диалог — /ai_reset."
)
AI_DISABLED = "Помощник пока недоступен. Кнопки календаря и дайджесты работают как обычно."
AI_BUSY = "Сейчас разбираю другие запросы. Попробуй ещё раз через минуту."
AI_ERROR = "Не удалось закончить запрос. Попробуй чуть позже или воспользуйся кнопками календаря."
AI_BUDGET = "Месячный лимит помощника исчерпан. Он возобновит работу в следующем месяце. Календарь и дайджесты продолжают работать."
AI_PRIVATE = "Помощник по личному календарю работает в личном чате со мной."
AI_RESET = "Начали новый диалог. История расходов и подтверждённых действий сохранена."
AI_NEED_DETAILS = "Уточни название, дату, время начала и длительность или время окончания встречи."
AI_NEED_MOVE = "Какую встречу и на какое время перенести? Можно указать название и дату или номер из последнего списка."
AI_NOT_FOUND = "Подходящих встреч не нашла. Уточни название или период поиска."
AI_SELECTION = "Нашла несколько встреч. Укажи номер нужной:\n\n{options}"
AI_CONFLICT = "## Это время занято\n\n{events}\n\n{alternatives}\n\nЕсли пересечение допустимо, напиши: «Да, несмотря на пересечение»."
AI_NO_ALTERNATIVES = "Свободных вариантов в этот день не нашла."
AI_ALTERNATIVES = "Свободные варианты: {slots}"
AI_UNCONFIRMED = "Не удалось подтвердить изменение в календаре. Я сохранила результат попытки и не буду повторять запись вслепую. Проверь встречу в календаре перед новой командой."
AI_EVENT_CHANGED = "Встреча или подключение изменились. Обнови список и уточни перенос ещё раз."
AI_NOT_ORGANIZER = "Эту встречу создал другой организатор. Попроси его изменить время."
AI_TIMED_ONLY = "Пока могу переносить только встречи с указанным временем, по одной дате серии."
AI_FOCUS_TITLE = "Время для сосредоточенной работы"
AI_OPTIMIZE_REQUEST = "Дай советы, как оптимизировать мой календарь на следующие семь дней: фокус, перерывы и равномерная нагрузка."
AI_WRITE_FORBIDDEN = "Календарь «{calendar}» не разрешает запись. Изменение не выполнено."
AI_NO_ACCESS = "Эта команда доступна только администратору."
AI_READ_FALLBACK = "Данные календаря получены, но не удалось подготовить объяснение. Попробуй ещё раз или открой «Ближайшие события»."


def _day_label(value: datetime) -> str:
    return f"{WEEKDAY_SHORT_RU[value.weekday()].capitalize()}, {value:%d.%m}"


def _zone_label(value: str) -> str:
    return "МСК" if value == "Europe/Moscow" else value


def _time_range(start: datetime, end: datetime) -> str:
    finish = end.strftime("%H:%M") if start.date() == end.date() else end.strftime("%d.%m %H:%M")
    return f"{start:%H:%M}–{finish}"


def _one_line(value: str) -> str:
    return " ".join(value.split())


def ai_calendar_choice(names: list[str]) -> str:
    if not names:
        return "Включи в настройках календарь с правом записи и повтори запрос."
    choices = "\n".join(f"• {_one_line(name)}" for name in names)
    return (
        "В какой календарь записать?\n\n"
        + choices
        + f"\n\nНапиши, например: «В календаре {_one_line(names[0])}»."
    )


def ai_conflict_events(events: list[dict]) -> str:
    lines = []
    for event in events:
        start, end = datetime.fromisoformat(event["start"]), datetime.fromisoformat(event["end"])
        lines.append(
            f"• {_one_line(event['title'])} — {_day_label(start)}, {_time_range(start, end)}"
        )
    return "\n".join(lines)


def ai_receipt(*, moved: bool, title: str, calendar: str, start: datetime, end: datetime) -> str:
    action = "Перенесла" if moved else "Создала"
    return (
        f"## ✅ {action} «{_one_line(title)}»\n\n"
        f"{_day_label(start)} · {_time_range(start, end)} · {_zone_label(str(start.tzinfo))}\n"
        f"Календарь: {_one_line(calendar)}"
    )


def ai_usage_text(usage: dict, limit: int) -> str:
    spent = usage["cost"] / 1_000_000_000
    blocks = [
        f"## Расходы ИИ · {usage['month']}",
        f"Потрачено: ${spent:.4f} из ${limit}\nОсталось: ${max(0, limit - spent):.4f}",
        f"Запросов: {usage['requests']}\nОшибок: {usage['errors']}\n"
        f"Незавершённых резервов: {usage['reserved']}",
        "Учитывается номинальная стоимость, включая запросы за бонусные средства.",
    ]
    if usage["users"]:
        blocks.append("## По пользователям")
        blocks.append(
            "\n".join(
                f"• {uid}: ${user['cost'] / 1_000_000_000:.4f}, запросов {user['requests']}"
                for uid, user in usage["users"].items()
            )
        )
    return "\n\n".join(blocks)


def ai_report_text(report: dict) -> str:
    """Human-readable blocks; option numbers and benefits remain server-owned."""
    first = datetime.fromisoformat(report["from_date"])
    end = report.get("to_date_exclusive") or report.get("to_date")
    assert isinstance(end, str)
    last = datetime.fromisoformat(end) - timedelta(days=1)
    period = (
        first.strftime("%d.%m") if first.date() == last.date() else f"{first:%d.%m}–{last:%d.%m}"
    )
    zone = _zone_label(report["timezone"])
    if "candidates" in report:
        blocks = [f"## 💡 Советы по календарю\n{period} · {zone}"]
        metrics = report["metrics"]
        blocks.extend(
            [
                "## Сейчас",
                f"• Пересечений: {metrics['overlaps']}\n"
                f"• Коротких перерывов: {metrics['short_breaks']}\n"
                f"• Окон для фокуса: {metrics['focus_windows']}",
            ]
        )
        labels = {
            "overlaps": "Пересечения",
            "outside_minutes": "Вне рабочего времени, мин",
            "short_breaks": "Короткие перерывы",
            "focus_windows": "Окна для фокуса",
            "load_spread_minutes": "Разница загрузки дней, мин",
        }
        for candidate in report["candidates"]:
            start, finish = (
                datetime.fromisoformat(candidate["start"]),
                datetime.fromisoformat(candidate["end"]),
            )
            proposed = f"{_day_label(start)} · {_time_range(start, finish)}"
            if candidate["kind"] == "focus":
                blocks.append(
                    f"{candidate['option']}. Выделить время для фокуса\n"
                    f"{proposed}\n"
                    f"Время для фокуса: 0 → {candidate['after']['reserved_focus_minutes']} мин"
                )
            else:
                before = datetime.fromisoformat(candidate["original_start"])
                changes = "\n".join(
                    f"• {label}: {candidate['before'][key]} → {candidate['after'][key]}"
                    for key, label in labels.items()
                    if candidate["before"][key] != candidate["after"][key]
                )
                blocks.append(
                    f"{candidate['option']}. Перенести «{_one_line(candidate['title'])}»\n"
                    f"Сейчас: {_day_label(before)} · {before:%H:%M}\n"
                    f"Предлагаю: {proposed}\n{changes}"
                )
        if report["candidates"]:
            blocks.append("## Как применить\nНапиши «Примени вариант 1» или укажи другой номер.")
            blocks.append(
                "Варианты независимы: после каждого изменения проверю расписание заново. Занятость остальных участников мне неизвестна."
            )
        else:
            blocks.append(
                "Подходящих перестановок или свободного окна для фокуса при этих настройках нет."
            )
        if any("unverified" in item for item in report["limitations"]):
            blocks.append(
                "Часть ответов на приглашения не удалось проверить; их время считаю занятым."
            )
        if any("first_200" in item for item in report["limitations"]):
            blocks.append("Учтены все встречи; варианты переноса проверены для первых 200.")
    else:
        slots = "options" in report
        heading = "🕒 Свободное время" if slots else "📅 Твой календарь"
        one_day = first.date() == last.date()
        if one_day:
            heading = (
                f"🕒 Свободное время · {_day_label(first)}" if slots else f"📅 {_day_label(first)}"
            )
        blocks = [f"## {heading} · {zone}" if one_day else f"## {heading}\n{period} · {zone}"]
        values = report.get("options", []) if slots else report.get("events", [])
        calendars = {e.get("calendar") for e in values if e.get("calendar")}
        if not slots and len(calendars) == 1:
            blocks[0] += f"\nКалендарь: {_one_line(next(iter(calendars)))}"
        previous_day = None
        for item in values:
            start, finish = (
                datetime.fromisoformat(item["start"]),
                datetime.fromisoformat(item["end"]),
            )
            if start.date() != previous_day and (not one_day or start.date() != first.date()):
                blocks.append(f"## {_day_label(start)}")
                previous_day = start.date()
            when = "Весь день" if item.get("all_day") else _time_range(start, finish)
            if item.get("all_day") and (finish - timedelta(microseconds=1)).date() > start.date():
                last_day = finish - timedelta(microseconds=1)
                when += f" · {start:%d.%m}–{last_day:%d.%m}"
            line = f"{item['option']}. {when}"
            if not slots:
                line += f" {_one_line(item['title'])}"
                if len(calendars) > 1 and item.get("calendar"):
                    line += f" · Календарь: {_one_line(item['calendar'])}"
            blocks.append(line)
        if not values:
            blocks.append(
                "Подходящих свободных окон нет."
                if slots
                else "В этом периоде подходящих событий нет."
            )
    if report.get("truncated"):
        blocks.append("Показана часть результатов. Уточни период или название для остальных.")
    return "\n\n".join(blocks)

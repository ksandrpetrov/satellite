"""Календарный помощник: интерфейс и проверенные подтверждения действий."""

from datetime import datetime, timedelta

AI_HELP = (
    "🪶 Теперь можно написать обычным сообщением:\n"
    "• Когда завтра найдётся час без встреч?\n"
    "• Найди встречи с командой на следующей неделе.\n"
    "• Создай «Подготовка отчёта» завтра с 15:00 до 16:00.\n"
    "• Перенеси завтрашнюю подготовку отчёта на час позже.\n"
    "• Как выглядит мой день или следующая неделя?\n"
    "• Как лучше организовать мой календарь?\n\n"
    "Однозначную просьбу создать или перенести встречу выполняю сразу. "
    "При совпадении названий или пересечении времени сначала уточню. "
    "Повторяющуюся встречу переношу только на выбранную дату.\n"
    "Советы — /optimize. Начать новый диалог — /ai_reset.\n\n"
    "Для ответа передаю в OpenAI текст запроса, названия и время нужных событий. "
    "Контекст диалога храню зашифрованным и использую до 24 часов после последнего сообщения."
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
AI_SELECTION = "Нашла несколько встреч. Укажи номер нужной:\n{options}"
AI_CONFLICT = "Это время занято:\n{events}\n\n{alternatives}\nЕсли пересечение допустимо, напиши: «Да, несмотря на пересечение»."
AI_NO_ALTERNATIVES = "Свободных вариантов в этот день не нашла."
AI_ALTERNATIVES = "Свободные варианты: {slots}"
AI_UNCONFIRMED = "Не удалось подтвердить изменение в календаре. Я сохранила результат попытки и не буду повторять запись вслепую. Проверь встречу в календаре перед новой командой."
AI_EVENT_CHANGED = "Встреча или подключение изменились. Обнови список и уточни перенос ещё раз."
AI_NOT_ORGANIZER = "Эту встречу создал другой организатор. Попроси его изменить время."
AI_TIMED_ONLY = "Пока могу переносить только встречи с указанным временем, по одной дате серии."
AI_FOCUS_TITLE = "Время для сосредоточенной работы"
AI_OPTIMIZE_REQUEST = "Дай советы, как оптимизировать мой календарь на следующие семь дней: фокус, перерывы и равномерная нагрузка."
AI_NO_ACCESS = "Эта команда доступна только администратору."
AI_READ_FALLBACK = "Данные календаря получены, но не удалось подготовить объяснение. Попробуй ещё раз или открой «Ближайшие события»."


def ai_receipt(*, moved: bool, title: str, calendar: str, start: str, end: str) -> str:
    action = "Перенесла" if moved else "Создала"
    return f"✅ {action} «{title}».\n{start} — {end}\nКалендарь: {calendar}."


def ai_usage_text(usage: dict, limit: int) -> str:
    spent = usage["cost"] / 1_000_000_000
    lines = [
        f"Расходы ИИ за {usage['month']}: ${spent:.4f} из ${limit}.",
        f"Осталось: ${max(0, limit - spent):.4f}.",
        f"Запросов: {usage['requests']}; ошибок: {usage['errors']}; незавершённых резервов: {usage['reserved']}.",
        "Учитывается номинальная стоимость, включая запросы за бонусные средства.",
    ]
    for uid, user in usage["users"].items():
        lines.append(
            f"Пользователь {uid}: ${user['cost'] / 1_000_000_000:.4f}, запросов {user['requests']}."
        )
    return "\n".join(lines)


def ai_report_text(report: dict) -> str:
    """Stable numbering and numeric evidence come from code, never a model rewrite."""

    def moment(value: str) -> str:
        return datetime.fromisoformat(value).strftime("%d.%m %H:%M")

    end = report.get("to_date_exclusive") or report.get("to_date")
    assert isinstance(end, str)
    last_day = (datetime.fromisoformat(end) - timedelta(days=1)).strftime("%d.%m")
    first_day = datetime.fromisoformat(report["from_date"]).strftime("%d.%m")
    lines = [f"📅 {first_day}–{last_day} · {report['timezone']}"]
    if "candidates" in report:
        metrics = report["metrics"]
        lines.append(
            f"Пересечений: {metrics['overlaps']}; коротких перерывов: {metrics['short_breaks']}; "
            f"окон для фокуса: {metrics['focus_windows']}."
        )
        labels = {
            "overlaps": "Пересечения",
            "outside_minutes": "Минуты вне рабочего времени",
            "short_breaks": "Короткие перерывы",
            "focus_windows": "Окна для фокуса",
            "load_spread_minutes": "Разница загрузки дней, мин",
        }
        for candidate in report["candidates"]:
            start, finish = moment(candidate["start"]), moment(candidate["end"])
            if candidate["kind"] == "focus":
                lines.append(
                    f"{candidate['option']}. Выделить время для фокуса: {start}–{finish}. "
                    f"Зарезервировано для фокуса: 0 → {candidate['after']['reserved_focus_minutes']} мин."
                )
            else:
                changes = [
                    f"{label}: {candidate['before'][key]} → {candidate['after'][key]}"
                    for key, label in labels.items()
                    if candidate["before"][key] != candidate["after"][key]
                ]
                lines.append(
                    f"{candidate['option']}. «{candidate['title']}»: {moment(candidate['original_start'])} → {start}–{finish}.\n"
                    + "; ".join(changes)
                    + "."
                )
        if not report["candidates"]:
            lines.append(
                "Не нашла подходящих перестановок или свободного окна для фокуса при этих настройках."
            )
        lines.append(
            "Это отдельные варианты. Чтобы применить один, напиши «Примени вариант 1». Занятость остальных участников мне неизвестна."
        )
        if any("unverified" in item for item in report["limitations"]):
            lines.append(
                "Часть ответов на приглашения не удалось проверить; их время считаю занятым."
            )
        if any("first_200" in item for item in report["limitations"]):
            lines.append(
                "В расчёте учтены все встречи; варианты переноса проверены для первых 200."
            )
    elif "options" in report:
        for option in report["options"]:
            lines.append(f"{option['option']}. {moment(option['start'])}–{moment(option['end'])}")
        if not report["options"]:
            lines.append("Подходящих свободных окон в этом периоде нет.")
    else:
        for event in report.get("events", []):
            lines.append(
                f"{event['option']}. {event['title']} — {moment(event['start'])}–{moment(event['end'])} · {event['calendar']}"
            )
        if not report.get("events"):
            lines.append("В этом периоде подходящих событий нет.")
    if report.get("truncated"):
        lines.append("Показана часть результатов. Уточни период или название для остальных.")
    return "\n\n".join(lines)

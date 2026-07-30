"""User-facing strings — ответы на встречи: /invitations и /manage (PARTSTAT)."""

from __future__ import annotations

from html import escape

from ..presentation.html import expandable_blockquote
from .buttons import styled_button
from .settings_ui import CB_SETTINGS_CALENDAR_BACK

# --- приглашения (PARTSTAT) --------------------------------------------------

CB_INV_CLOSE = "inv:close"
CB_INV_REFRESH = "inv:refresh"
CB_INV_RESPOND_PREFIX = "inv:r:"

INVITATIONS_FETCH_STATUS = "📨 Чайка собирает приглашения…"
INVITATIONS_BUSY_TEXT = "📨 Уже собираю приглашения — секунду."
INVITATIONS_EMPTY_HTML = (
    "📨 <b>Приглашения</b>\n\nВсё разобрано — встреч, где нужно принять решение, сейчас нет."
)
INVITATIONS_INTRO_HTML = (
    "<b>Приглашения</b>\n\n"
    "Встречи, где тебя ждут как участника. Нажми кнопку под событием — "
    "ответ улетит в календарь."
)
INVITATIONS_RESPOND_ACCEPTED = "Принято"
INVITATIONS_RESPOND_DECLINED = "Отклонено"
INVITATIONS_RESPOND_TENTATIVE = "Может быть"
INVITATIONS_RESPOND_FAIL_TEXT = "Не удалось обновить ответ. Попробуй позже."
INVITATIONS_CLOSED_TEXT = "📨 Чайка свернула список приглашений."


def build_invitations_keyboard(
    events: list[tuple[str, str]],
    *,
    from_settings_hub: bool = False,
) -> dict:
    """Inline-клавиатура: по строке кнопок на каждое событие (token, label index).

    ``from_settings_hub=True`` — «⬅️ В календарь» + «Закрыть»; иначе только «Закрыть».
    """
    rows: list[list[dict[str, str]]] = []
    for token, label in events:
        rows.append(
            [
                styled_button(
                    f"✅ {label}",
                    f"{CB_INV_RESPOND_PREFIX}{token}:a",
                    style="success",
                ),
                styled_button(
                    f"❌ {label}",
                    f"{CB_INV_RESPOND_PREFIX}{token}:d",
                    style="danger",
                ),
                styled_button(
                    f"🤔 {label}",
                    f"{CB_INV_RESPOND_PREFIX}{token}:t",
                    style="primary",
                ),
            ]
        )
    rows.append([{"text": "🔄 Обновить", "callback_data": CB_INV_REFRESH}])
    if from_settings_hub:
        rows.append(
            [
                {"text": "⬅️ В календарь", "callback_data": CB_SETTINGS_CALENDAR_BACK},
                {"text": "⬅️ Закрыть", "callback_data": CB_INV_CLOSE},
            ]
        )
    else:
        rows.append([{"text": "⬅️ Закрыть", "callback_data": CB_INV_CLOSE}])
    return {"inline_keyboard": rows}


def invitations_list_html(
    *,
    body_lines: list[str],
    preview_title: str,
    preview_when: str,
    truncated: bool,
) -> str:
    preview = f"📨 <b>{escape(preview_title, quote=False)}</b>\n🗓 {escape(preview_when)}"
    parts = [preview, "", INVITATIONS_INTRO_HTML]
    if body_lines:
        parts.append("")
        body = "\n".join(body_lines)
        parts.append(expandable_blockquote(body, threshold=4))
    if truncated:
        parts.append("")
        parts.append("<i>Показаны первые встречи — обновите список после ответов.</i>")
    return "\n".join(parts)


# --- изменение статуса встречи (PARTSTAT) ----------------------------------

CB_MANAGE_CLOSE = "mng:close"
CB_MANAGE_BACK = "mng:back"
CB_MANAGE_REFRESH = "mng:refresh"
CB_MANAGE_PICK_PREFIX = "mng:p:"
CB_MANAGE_RESPOND_PREFIX = "mng:r:"

MANAGE_FETCH_STATUS = "🛠 Чайка собирает встречи на неделе…"
MANAGE_BUSY_TEXT = "🛠 Уже собираю встречи — секунду."
MANAGE_INTRO_HTML = (
    "🛠 <b>Изменить статус встречи</b>\n\n"
    "Встречи на ближайшие 7 дней, где ты участник. Тапни строку — Чайка покажет, "
    "что можно поменять: ✅ принять, 🤔 может быть, ❌ отклонить.\n\n"
    "<i>Отклонённые встречи Чайка не показывает в плане и дайджесте.</i>"
)
MANAGE_EMPTY_HTML = (
    "🛠 <b>Изменить статус встречи</b>\n\n"
    "На ближайшую неделю встреч, где ты участник, не нашлось — менять статус нечему."
)
MANAGE_CLOSED_TEXT = "🛠 Чайка свернула список встреч."
MANAGE_NOT_FOUND_TEXT = "Встреча не нашлась — обновите список."
MANAGE_RESPOND_FAIL_TEXT = "Не удалось обновить статус. Попробуй позже."
MANAGE_RESPOND_ACCEPTED = "✅ Принято"
MANAGE_RESPOND_DECLINED = "❌ Отклонено"
MANAGE_RESPOND_TENTATIVE = "🤔 Может быть"

_MANAGE_PARTSTAT_LABEL_RU = {
    "ACCEPTED": "✅ принято",
    "TENTATIVE": "🤔 может быть",
    "DECLINED": "❌ отклонено",
    "NEEDS-ACTION": "📨 ждёт ответа",
    "DELEGATED": "↪️ делегировано",
}


def manage_partstat_label(partstat: str | None) -> str | None:
    if not partstat:
        return None
    return _MANAGE_PARTSTAT_LABEL_RU.get(partstat.strip().upper())


def manage_detail_html(*, title: str, when: str, partstat: str | None) -> str:
    label = manage_partstat_label(partstat) or "—"
    return (
        f"🛠 <b>{title}</b>\n"
        f"{when}\n\n"
        f"📌 Сейчас: <b>{label}</b>\n\n"
        "<i>Поменять решение можно сколько угодно — Чайка пошлёт ответ в календарь.</i>"
    )


def build_manage_list_keyboard(rows: list[tuple[str, str]]) -> dict:
    """rows: [(token, label like '1️⃣ 14:00 — Standup')]."""
    inline: list[list[dict[str, str]]] = []
    for token, label in rows:
        clipped = label if len(label) <= 60 else label[:57] + "…"
        inline.append([{"text": clipped, "callback_data": f"{CB_MANAGE_PICK_PREFIX}{token}"}])
    inline.append([{"text": "🔄 Обновить", "callback_data": CB_MANAGE_REFRESH}])
    inline.append([{"text": "⬅️ Закрыть", "callback_data": CB_MANAGE_CLOSE}])
    return {"inline_keyboard": inline}


def build_manage_detail_keyboard(token: str, *, partstat: str | None) -> dict:
    cur = (partstat or "").strip().upper()
    mark = lambda code, label: f"{label} ✓" if cur == code else label  # noqa: E731
    return {
        "inline_keyboard": [
            [
                styled_button(
                    mark("ACCEPTED", "✅ Принять"),
                    f"{CB_MANAGE_RESPOND_PREFIX}{token}:a",
                    style="success",
                ),
                styled_button(
                    mark("TENTATIVE", "🤔 Может быть"),
                    f"{CB_MANAGE_RESPOND_PREFIX}{token}:t",
                    style="primary",
                ),
            ],
            [
                styled_button(
                    mark("DECLINED", "❌ Отклонить"),
                    f"{CB_MANAGE_RESPOND_PREFIX}{token}:d",
                    style="danger",
                ),
            ],
            [{"text": "⬅️ К списку", "callback_data": CB_MANAGE_BACK}],
        ]
    }


def manage_list_html(*, body_lines: list[str], truncated: bool) -> str:
    parts = [MANAGE_INTRO_HTML]
    if body_lines:
        parts.append("")
        body = "\n".join(body_lines)
        parts.append(expandable_blockquote(body, threshold=4))
    if truncated:
        parts.append("")
        parts.append("<i>Показаны первые встречи — обновите список после изменений.</i>")
    return "\n".join(parts)

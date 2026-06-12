"""User-facing strings — админ: заявки и /pending."""

from __future__ import annotations

from .buttons import styled_button

# --- Admin ---
CB_ADMIN_APPROVE_PREFIX = "admin:approve:"
CB_ADMIN_REJECT_PREFIX = "admin:reject:"
CMD_PENDING = "/pending"


def admin_access_request_html(
    *, display_name: str | None, username: str | None, telegram_user_id: int
) -> str:
    name = display_name or "—"
    uname = f"@{username}" if username else "—"
    return (
        "👤 Новый пользователь стучится к Чайке:\n"
        f"Имя: {name}\n"
        f"Username: {uname}\n"
        f"Telegram ID: {telegram_user_id}"
    )


def build_admin_access_keyboard(*, telegram_user_id: int) -> dict:
    return {
        "inline_keyboard": [
            [
                styled_button(
                    "✅ Разрешить",
                    f"{CB_ADMIN_APPROVE_PREFIX}{telegram_user_id}",
                    style="success",
                ),
                styled_button(
                    "❌ Отклонить",
                    f"{CB_ADMIN_REJECT_PREFIX}{telegram_user_id}",
                    style="danger",
                ),
            ]
        ]
    }


def admin_pending_list_html(lines: list[str]) -> str:
    if not lines:
        return "📋 Нет заявок на рассмотрении."
    body = "\n".join(f"• {line}" for line in lines)
    return f"📋 Заявки на доступ:\n{body}"


ADMIN_ACTION_FORBIDDEN_HTML = "⛔️ Эта команда доступна только администратору."

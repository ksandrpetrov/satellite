"""Общий слой между ``/invitations`` и ``/manage`` для ответа PARTSTAT.

Оба сценария отличаются только текстами, prefix'ом callback'а, источником
событий и тем, что показывать при «событие пропало» / «успех». Сам поток
(распарсить ``token:code`` → найти event → ``set_attendee_partstat`` →
обновить экран) идентичен — он живёт здесь.

Хендлеры (:mod:`.calendar_invitations`, :mod:`.calendar_manage`) собирают
:class:`PartstatFlow`-конфиг и вызывают :func:`respond_partstat`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ...calendar.callback_tokens import event_callback_token
from ...calendar.providers.base import (
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from .context import HandlerContext, IncomingCallback
from .delivery import safe_answer_callback

log = logging.getLogger(__name__)

PARTSTAT_BY_CODE: Mapping[str, str] = {
    "a": "ACCEPTED",
    "d": "DECLINED",
    "t": "TENTATIVE",
}


def find_event_by_token(events: list, token: str):
    """Ищет событие по токену кнопки среди полной выдачи (не только pending).

    При повторном CalDAV REPORT Mail.ru часто не отдаёт PARTSTAT в ATTENDEE,
    и событие выпадает из ``pending``, хотя URL тот же — ответ на приглашение
    всё равно нужно отправить по этому URL.
    """
    needle = (token or "").strip()
    if not needle:
        return None
    for ev in events:
        if event_callback_token(str(ev.get("url") or "")) == needle:
            return ev
    return None


def parse_respond_data(data: str, prefix: str) -> tuple[str, str, str] | None:
    """Возвращает ``(token, code, partstat)`` или ``None`` при невалидном payload."""
    if not data.startswith(prefix):
        return None
    suffix = data[len(prefix) :]
    if ":" not in suffix:
        return None
    token, raw_code = suffix.rsplit(":", 1)
    code = raw_code.strip().lower()
    partstat = PARTSTAT_BY_CODE.get(code)
    if not partstat:
        return None
    return token, code, partstat


@dataclass(frozen=True)
class PartstatFlow:
    """Конфигурация одного флоу ответа на встречу.

    Параметры:
    - ``prefix``: префикс callback_data (``inv:r:`` / ``mng:r:``).
    - ``fail_text``: toast при ошибке CalDAV / сетевой ошибке.
    - ``toast_by_code``: ``{'a': '...', 'd': '...', 't': '...'}`` — toast после
      успешного ответа.
    - ``log_name``: префикс для логов (``Invitation`` / ``Manage``).
    - ``fetch_events``: ``(ctx, user_id) -> list`` — полный список событий,
      в котором ищем по token (включая не-pending).
    - ``refresh_view``: ``(ctx, cb, toast | None)`` — перерисовать экран
      после ответа (показать обновлённый список / закрытие).
    - ``on_not_found``: ``(ctx, cb)`` — что делать, если event пропал
      (Mail.ru мог отдать иной ATTENDEE при следующем REPORT).
    - ``on_success``: ``(ctx, cb, code, toast)`` — побочные эффекты успеха
      (push с EFFECT_SPARKLES и т.п.).
    """

    prefix: str
    fail_text: str
    toast_by_code: Mapping[str, str]
    log_name: str
    fetch_events: Callable[[HandlerContext, int], list]
    refresh_view: Callable[[HandlerContext, IncomingCallback, str | None], None]
    on_not_found: Callable[[HandlerContext, IncomingCallback], None]
    on_success: Callable[[HandlerContext, IncomingCallback, str, str], None]


def respond_partstat(
    ctx: HandlerContext, cb: IncomingCallback, data: str, flow: PartstatFlow
) -> None:
    """Распарсить callback, найти event, выставить PARTSTAT, обновить экран."""
    if cb.user_id is None:
        safe_answer_callback(ctx, cb)
        return
    parsed = parse_respond_data(data, flow.prefix)
    if parsed is None:
        safe_answer_callback(ctx, cb)
        return
    token, code, partstat = parsed
    try:
        events = flow.fetch_events(ctx, cb.user_id)
        event = find_event_by_token(events, token)
        if event is None:
            log.warning(
                "%s respond: event not found by token user_id=%s token=%s",
                flow.log_name,
                cb.user_id,
                token,
            )
            flow.on_not_found(ctx, cb)
            return
        event_url = str(event.get("url") or "")
        uid = str(event.get("uid") or "")
        ctx.calendar_service.set_attendee_partstat(
            cb.user_id,
            CalendarEventRef(uid=uid, url=event_url),
            partstat,
        )
    except (CalendarNotConnectedError, CalendarProviderError) as exc:
        log.error(
            "%s respond failed user_id=%s: %s",
            flow.log_name,
            cb.user_id,
            getattr(exc, "error_code", exc.__class__.__name__),
        )
        safe_answer_callback(ctx, cb, text=flow.fail_text)
        return
    fallback_toast = next(iter(flow.toast_by_code.values()))
    toast = flow.toast_by_code.get(code, fallback_toast)
    flow.on_success(ctx, cb, code, toast)
    flow.refresh_view(ctx, cb, toast)

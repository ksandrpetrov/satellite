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
from ...calendar.event_token_cache import CachedEventRef, get_event_token_cache
from ...calendar.providers.base import (
    CalendarEventRef,
    CalendarNotConnectedError,
    CalendarProviderError,
)
from .action_guard import ActionGuard
from .context import HandlerContext, IncomingCallback
from .delivery import safe_answer_callback

log = logging.getLogger(__name__)

# Двойной клик по «Принять / Отклонить» одного приглашения: второй callback
# ждёт chat lock, потом делает повторный CalDAV PUT и шлёт повторный toast +
# эффект. Guard блокирует повтор пока CalDAV ещё идёт И ~5 с после успеха
# (отдельный ключ на каждое событие — другой токен значит другая встреча).
_PARTSTAT_RESPOND_COOLDOWN_SEC = 5.0
_partstat_respond_guard = ActionGuard(cooldown_sec=_PARTSTAT_RESPOND_COOLDOWN_SEC)

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


def _resolve_event_ref(
    ctx: HandlerContext,
    user_id: int,
    token: str,
    *,
    fetch_events: Callable[[HandlerContext, int], list],
) -> tuple[CachedEventRef | None, list | None]:
    """URL события из token-cache или fallback на полный CalDAV-лист."""
    cache = get_event_token_cache()
    cached = cache.lookup(user_id, token)
    if cached is not None:
        return cached, None
    events = fetch_events(ctx, user_id)
    event = find_event_by_token(events, token)
    if event is None:
        return None, events
    return (
        CachedEventRef(
            url=str(event.get("url") or ""),
            uid=str(event.get("uid") or ""),
        ),
        events,
    )


@dataclass(frozen=True)
class PartstatFlow:
    """Конфигурация одного флоу ответа на встречу.

    Параметры:
    - ``prefix``: префикс callback_data (``inv:r:`` / ``mng:r:``).
    - ``fail_text``: toast при ошибке CalDAV / сетевой ошибке.
    - ``toast_by_code``: ``{'a': '...', 'd': '...', 't': '...'}`` — toast после
      успешного ответа.
    - ``log_name``: префикс для логов (``Invitation`` / ``Manage``).
    - ``fetch_events``: ``(ctx, user_id) -> list`` — полный список событий
      при cache miss (включая не-pending).
    - ``optimistic_refresh_view``: перерисовать экран из кэша без CalDAV;
      ``fallback_events`` — результат единственного fallback-fetch при cache miss.
    - ``on_not_found``: ``(ctx, cb)`` — событие не найдено даже после fallback.
    - ``on_fail``: ``(ctx, cb)`` — CalDAV PUT не удался (callback уже ack).
    """

    prefix: str
    fail_text: str
    toast_by_code: Mapping[str, str]
    log_name: str
    fetch_events: Callable[[HandlerContext, int], list]
    optimistic_refresh_view: Callable[
        [HandlerContext, IncomingCallback, str, str, list | None],
        None,
    ]
    on_not_found: Callable[[HandlerContext, IncomingCallback], None]
    on_fail: Callable[[HandlerContext, IncomingCallback], None]


def respond_partstat(
    ctx: HandlerContext, cb: IncomingCallback, data: str, flow: PartstatFlow
) -> None:
    """Распарсить callback, найти event, выставить PARTSTAT, обновить экран."""
    if cb.user_id is None or cb.chat_id is None:
        safe_answer_callback(ctx, cb)
        return
    parsed = parse_respond_data(data, flow.prefix)
    if parsed is None:
        safe_answer_callback(ctx, cb)
        return
    token, code, partstat = parsed
    action_key = f"{flow.prefix}{token}"
    if not _partstat_respond_guard.try_acquire(cb.chat_id, action_key):
        # Дубль того же ответа на ту же встречу: молча ack-аем callback,
        # чтобы Telegram-кнопка не «вращалась», но никаких send/effect/toast.
        safe_answer_callback(ctx, cb)
        return
    sent = False
    try:
        event_ref, fallback_events = _resolve_event_ref(
            ctx,
            cb.user_id,
            token,
            fetch_events=flow.fetch_events,
        )
        if event_ref is None or not event_ref.url:
            log.warning(
                "%s respond: event not found by token user_id=%s token=%s",
                flow.log_name,
                cb.user_id,
                token,
            )
            flow.on_not_found(ctx, cb)
            return
        fallback_toast = next(iter(flow.toast_by_code.values()))
        toast = flow.toast_by_code.get(code, fallback_toast)
        safe_answer_callback(ctx, cb, text=toast)
        try:
            ctx.calendar_service.set_attendee_partstat(
                cb.user_id,
                CalendarEventRef(uid=event_ref.uid, url=event_ref.url),
                partstat,
            )
        except (CalendarNotConnectedError, CalendarProviderError) as exc:
            log.error(
                "%s respond failed user_id=%s: %s",
                flow.log_name,
                cb.user_id,
                getattr(exc, "error_code", exc.__class__.__name__),
            )
            flow.on_fail(ctx, cb)
            return
        flow.optimistic_refresh_view(ctx, cb, token, partstat, fallback_events)
        sent = True
    finally:
        _partstat_respond_guard.release(cb.chat_id, action_key, sent=sent)

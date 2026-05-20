"""Низкоуровневые Telegram-операции: send/edit/finalize/answer-callback.

Здесь собрана вся обвязка вокруг ``TelegramClient`` так, чтобы хендлеры
сценариев не знали про детали send/edit и обработку ошибок отправки.
"""

from __future__ import annotations

import logging

from ...messages_ru import ERR_GENERIC_HANDLER_TEXT
from ..api import TelegramError
from ..message_editing import edit_or_send_message
from .context import HandlerContext, IncomingCallback

log = logging.getLogger(__name__)


def send(ctx: HandlerContext, chat_id: int | None, text: str) -> None:
    """Отправка обычного сообщения без reply-клавиатуры.

    Старая нижняя Reply-клавиатура больше не отправляется — основная навигация
    теперь живёт в меню команд Telegram. На /start и /help отправляется
    отдельно ``ReplyKeyboardRemove``, чтобы убрать клавиатуру у пользователей,
    подключившихся до миграции.
    """
    if chat_id is None:
        return
    ctx.telegram.send_message(chat_id, text)


def try_send_return_message_id(
    ctx: HandlerContext, chat_id: int | None, text: str
) -> int | None:
    """Как `send`, но возвращает ``message_id`` для последующего ``editMessageText``."""
    if chat_id is None:
        return None
    try:
        result = ctx.telegram.send_message(chat_id, text)
    except TelegramError as exc:
        log.warning("Failed to send status message: %s", exc)
        return None
    mid = result.get("message_id") if isinstance(result, dict) else None
    return int(mid) if isinstance(mid, int) else None


def finalize_message(
    ctx: HandlerContext,
    chat_id: int,
    loading_message_id: int | None,
    text: str,
) -> None:
    edit_or_send_message(
        ctx.telegram,
        chat_id,
        loading_message_id,
        text,
        reply_markup=None,
    )


def edit_callback_message(
    ctx: HandlerContext,
    cb: IncomingCallback,
    text: str,
    reply_markup: dict | None,
) -> None:
    """Редактирует сообщение, к которому привязана inline-кнопка.

    ВАЖНО: НИКОГДА не делаем fallback на ``send_message``. Иначе любой повторный
    callback (Telegram переотдаёт его при offset-рассинхроне или при двойном
    тапе пользователя) превращается в дубль сообщения «🕘 Напиши новое время…»
    и тому подобных экранов — пользователь видит спам. Если edit не удался,
    содержимое экрана у пользователя уже корректное (мы редактируем на ТО ЖЕ
    состояние, что и в прошлый раз), либо это устаревший callback, который уже
    отработан. В обоих случаях молча выходим.
    """
    if cb.chat_id is None or cb.message_id is None:
        return
    try:
        ctx.telegram.edit_message_text(
            cb.chat_id,
            cb.message_id,
            text,
            reply_markup=reply_markup,
        )
    except TelegramError as exc:
        log.info("Edit callback message ignored: %s", exc)


def safe_answer_callback(
    ctx: HandlerContext, cb: IncomingCallback, *, text: str | None = None
) -> None:
    try:
        ctx.telegram.answer_callback_query(cb.callback_query_id, text=text)
    except TelegramError as exc:
        log.info("answerCallbackQuery failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - callback ack не должен валить handler
        log.warning("Unexpected answerCallbackQuery failure: %s", exc)


def webapp_connect_url(ctx: HandlerContext) -> str:
    """Базовый URL Web App для подключения календаря.

    Дописывает суффикс ``/connect`` если ``WEBAPP_BASE_URL`` указан без него.
    Используется во всех точках входа (`/start`, approve, кнопки настроек,
    подэкран «Календарь») — чтобы не дублировать нормализацию пути.
    """
    base = (ctx.webapp.base_url or "").rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/connect") else f"{base}/connect"


def notify_handler_failure(ctx: HandlerContext, chat_id: int | None) -> None:
    """Best-effort отправка нейтрального текста при необработанной ошибке хендлера.

    Все исключения подавляем — мы уже в ветке обработки исходного сбоя и не
    должны мешать диспетчеру логировать первопричину. AGENTS #5: пользователь
    видит безопасный текст, не стек.
    """
    if chat_id is None:
        return
    try:
        ctx.telegram.send_message(chat_id, ERR_GENERIC_HANDLER_TEXT)
    except Exception as exc:  # noqa: BLE001 - вторая ошибка не должна валить процесс
        log.warning("Failed to send generic error notice: %s", exc)

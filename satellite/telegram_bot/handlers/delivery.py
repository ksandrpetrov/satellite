"""Низкоуровневые Telegram-операции: streaming/edit-callback/answer-callback.

Здесь собрана вся обвязка вокруг ``TelegramClient`` так, чтобы хендлеры
сценариев не знали про детали send/edit и обработку ошибок отправки.
Промежуточная доставка длинных ответов — через :mod:`..streaming_delivery`.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from ...config import WebAppConfig
from ...messages_ru import ERR_GENERIC_HANDLER_TEXT
from ..api import TelegramError
from ..message_delivery import edit_rich_or_html
from ..streaming_delivery import StreamingReply
from ..streaming_delivery import open_streaming_reply as _open_streaming_reply
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


def open_streaming_reply(
    ctx: HandlerContext,
    chat_id: int,
    initial_text: str = "",
    *,
    draft_id: int | None = None,
    message_thread_id: int | None = None,
    chat_action: str | None = "typing",
    rich: bool = False,
) -> StreamingReply:
    """Потоковый ответ: ``sendMessageDraft`` с fallback на loading+edit.

    Пустой ``initial_text`` (по умолчанию) → нативный «Thinking…» из Bot API
    10.0; на старых серверах сервис подставит ``⏳`` placeholder.
    """
    return _open_streaming_reply(
        ctx.telegram,
        chat_id,
        initial_text,
        draft_id=draft_id,
        message_thread_id=message_thread_id,
        chat_action=chat_action,
        rich=rich,
    )


def edit_callback_rich_or_html(
    ctx: HandlerContext,
    cb: IncomingCallback,
    *,
    rich_html: str,
    fallback_html: str,
    reply_markup: dict | None,
) -> None:
    """Редактирует callback-сообщение rich HTML с fallback."""
    if cb.chat_id is None or cb.message_id is None:
        return
    try:
        edit_rich_or_html(
            ctx.telegram,
            cb.chat_id,
            cb.message_id,
            rich_html=rich_html,
            fallback_html=fallback_html,
            reply_markup=reply_markup,
        )
    except TelegramError as exc:
        log.info("Edit callback rich message ignored: %s", exc)
    except Exception as error:  # noqa: BLE001
        log.warning("Unexpected error editing rich callback message: %s", error)


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
    ctx: HandlerContext,
    cb: IncomingCallback,
    *,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    try:
        if show_alert:
            ctx.telegram.answer_callback_query(
                cb.callback_query_id,
                text=text,
                show_alert=True,
            )
        else:
            ctx.telegram.answer_callback_query(cb.callback_query_id, text=text)
    except TelegramError as exc:
        log.info("answerCallbackQuery failed: %s", exc)
    except Exception as exc:  # noqa: BLE001 - callback ack не должен валить handler
        log.warning("Unexpected answerCallbackQuery failure: %s", exc)


def webapp_connect_base_url(webapp: WebAppConfig) -> str:
    """Публичный URL страницы ``/connect`` без персонального токена (menu Web App)."""
    base = (webapp.base_url or "").rstrip("/")
    if not base:
        return ""
    return base if base.endswith("/connect") else f"{base}/connect"


def webapp_connect_url(
    ctx: HandlerContext,
    telegram_user_id: int | None = None,
) -> str:
    """URL Web App для кнопки в чате.

    С ``telegram_user_id`` — ``/connect/<token>`` в пути (Telegram часто
    срезает query у ``web_app``-кнопок). Токен дублируется в HTML при отдаче
    страницы — см. ``_serve_connect_html``.
    """
    url = webapp_connect_base_url(ctx.webapp)
    if not url or telegram_user_id is None:
        return url
    token = ctx.connect_tokens.issue(telegram_user_id)
    if not isinstance(token, str) or not token.strip():
        return url
    # Путь + hash: Telegram иногда открывает только /connect без query/path.
    return f"{url}/{token.strip()}#t={quote(token.strip(), safe='')}"


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

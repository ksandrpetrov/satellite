"""Telegram Bot API error types and classification helpers."""

from __future__ import annotations


class TelegramError(RuntimeError):
    """Не получилось договориться с Telegram даже после всех ретраев."""


def is_custom_emoji_rejected(exc: BaseException) -> bool:
    """Telegram отклонил ``<tg-emoji emoji-id="…">`` в HTML-тексте.

    Возможные ответы Telegram:

    * ``CUSTOM_EMOJI_ID_INVALID`` / ``tg-emoji ...`` — известная нам форма,
      когда id отвергнут явно;
    * ``DOCUMENT_INVALID`` — приходит от ``sendMessage``/``editMessageText``,
      когда ``emoji-id`` ссылается на несуществующий sticker document
      (типично для ботов без купленного на Fragment имени: им custom emoji
      запрещены, и ``<tg-emoji>`` всегда указывает «в никуда»). В сообщении
      нет файла, поэтому ``DOCUMENT_INVALID`` может прийти только от
      кастомного эмодзи — безопасно трактовать как сигнал «снять теги».
    """
    text = str(exc).lower()
    return "custom_emoji" in text or "tg-emoji" in text or "document_invalid" in text


def is_html_entities_rejected(exc: BaseException) -> bool:
    """Невалидный HTML (entities, expandable blockquote, и т.п.)."""
    text = str(exc).lower()
    return (
        "can't parse" in text
        or "parse entities" in text
        or "unsupported start tag" in text
        or ("expandable" in text and "blockquote" in text)
    )


def is_rich_message_unavailable(exc: BaseException) -> bool:
    """``sendRichMessage`` / ``sendRichMessageDraft`` недоступны (старый Bot API)."""
    text = str(exc).lower()
    return (
        "sendrichmessage" in text
        or "rich_message" in text
        or "method is not found" in text
        or "method not found" in text
        or "unknown method" in text
        or "not implemented" in text
    )


def is_message_effect_rejected(exc: BaseException) -> bool:
    """Telegram отказался применять ``message_effect_id``.

    Возможные причины:

    * подписан как `Bad Request: message_effect_id ...` — невалидный/чужой id;
    * `Bad Request: PREMIUM_ACCOUNT_REQUIRED` — у получателя нет Telegram Premium,
      а анимированные эффекты доступны только премиум-чатам.

    Бот использует ``message_effect_id`` только в личных чатах и без других
    премиум-фич, поэтому такой ответ всегда означает «эффект применить нельзя»;
    повторяем отправку без эффекта.
    """
    text = str(exc).lower()
    return "message_effect" in text or "premium_account_required" in text

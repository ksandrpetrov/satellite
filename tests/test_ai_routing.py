"""Private chat, access control, command/FSM precedence and escaped output."""

from dataclasses import replace
from unittest.mock import MagicMock

from satellite.messages_ru import AI_PRIVATE, BOT_KEYBOARD_HINT, BUTTON_OPTIMIZE
from satellite.telegram_bot.handlers import handle_message
from satellite.telegram_bot.handlers.routing import OptimizeCommand, recognize_message
from satellite.testing.delivery_helpers import final_message_html

from .conftest import make_ctx, make_msg, make_user_store


def test_ai_handles_text_but_unknown_slash_and_create_fsm_keep_precedence(tmp_path):
    ctx = make_ctx(make_user_store(tmp_path, approved_with_calendar=[5001]))
    ctx.assistant = MagicMock()
    ctx.assistant.respond.return_value = "Встреча <script> & текст"
    ctx.subscriptions.get.return_value = None
    handle_message(ctx, make_msg(text="Как оптимизировать календарь?"))
    assert "&lt;script&gt; &amp;" in final_message_html(ctx.telegram)
    assert ctx.assistant.respond.call_count == 1
    handle_message(ctx, make_msg(text="/unknown", update_id=2))
    assert final_message_html(ctx.telegram) == BOT_KEYBOARD_HINT
    handle_message(ctx, make_msg(text="/create", update_id=3))
    handle_message(ctx, make_msg(text="Название встречи", update_id=4))
    assert ctx.assistant.respond.call_count == 1
    assert isinstance(recognize_message(BUTTON_OPTIMIZE), OptimizeCommand)
    assert recognize_message(" ") is None


def test_ai_rejects_group_and_unapproved_access(tmp_path):
    ctx = make_ctx(make_user_store(tmp_path, approved_with_calendar=[5001], pending=[5002]))
    ctx.assistant = MagicMock()
    handle_message(ctx, replace(make_msg(text="Мой календарь"), chat_id=-10, chat_type="group"))
    assert final_message_html(ctx.telegram) == AI_PRIVATE
    handle_message(ctx, make_msg(text="Мой календарь", user_id=5002, chat_id=5002, update_id=2))
    ctx.assistant.respond.assert_not_called()


def test_ai_reset_does_not_call_model_and_usage_is_admin_only(tmp_path):
    ctx = make_ctx(make_user_store(tmp_path, approved_with_calendar=[5001]))
    ctx.assistant = MagicMock()
    handle_message(ctx, make_msg(text="/ai_reset"))
    ctx.assistant.reset.assert_called_once_with(5001)
    handle_message(ctx, make_msg(text="/ai_usage", update_id=2))
    ctx.assistant.store.usage.assert_not_called()
    ctx.assistant.respond.assert_not_called()

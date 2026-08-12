"""Unit tests for WellsMiddleSchoolAgent."""
from unittest.mock import MagicMock, patch, call
import pytest

import app.agent as agent_module
from app.agent import WellsMiddleSchoolAgent
from app.store.redis_store import RedisStore
from tests.store.conftest import FakeRedisClient


@pytest.fixture()
def agent():
    with patch("app.agent.anthropic.Anthropic"):
        redis_store = RedisStore(client=FakeRedisClient())
        postgres_store = MagicMock()
        return WellsMiddleSchoolAgent(redis_store=redis_store, postgres_store=postgres_store)


def _text_response(text: str):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text=text, type="text")]
    return mock_response


# ── Prompt caching: system prompt is static ───────────────────────────────────

def test_system_prompt_has_no_today_placeholder(agent):
    assert "{today}" not in agent._SYSTEM_PROMPT


def test_system_prompt_is_stable_across_calls(agent):
    first = agent._SYSTEM_PROMPT
    second = agent._SYSTEM_PROMPT
    assert first == second


def test_system_prompt_allows_markdown(agent):
    assert "Markdown" in agent._SYSTEM_PROMPT
    assert "**bold**" in agent._SYSTEM_PROMPT


def test_chat_uses_system_prompt(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="u_web")

    _, kwargs = agent.client.beta.messages.create.call_args
    assert kwargs["system"][0]["text"] == agent._SYSTEM_PROMPT


# ── _call_api passes system as list with cache_control ────────────────────────

def test_call_api_system_is_list_with_cache_control(agent):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}])

    _, kwargs = agent.client.beta.messages.create.call_args
    system = kwargs["system"]
    assert isinstance(system, list)
    assert len(system) == 1
    assert system[0]["type"] == "text"
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["text"] == agent._SYSTEM_PROMPT


def test_call_api_includes_prompt_caching_beta(agent):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    agent.client.beta.messages.create.return_value = mock_response

    agent._call_api([{"role": "user", "content": "hi"}])

    # Regression guard: the betas= kwarg only exists on client.beta.messages.create
    # in anthropic==0.39.0; sending it to client.messages.create raises TypeError.
    agent.client.beta.messages.create.assert_called_once()
    agent.client.messages.create.assert_not_called()

    _, kwargs = agent.client.beta.messages.create.call_args
    assert "prompt-caching-2024-07-31" in kwargs.get("betas", [])


# ── Last tool has cache_control ───────────────────────────────────────────────

def test_last_tool_has_cache_control(agent):
    last_tool = agent.tools[-1]
    assert last_tool.get("cache_control") == {"type": "ephemeral"}


def test_non_last_tools_have_no_cache_control(agent):
    for tool in agent.tools[:-1]:
        assert "cache_control" not in tool


# ── Dynamic context injected into first user message only ─────────────────────

def test_dynamic_context_prepended_to_first_message(agent):
    agent.client.beta.messages.create.return_value = _text_response("Test response")

    with patch("app.agent.get_school_day_status", return_value="Regular school day"), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("What time does school start?", user_id="test_user")

    _, kwargs = agent.client.beta.messages.create.call_args
    first_message = kwargs["messages"][0]
    assert first_message["role"] == "user"
    assert first_message["content"].startswith("[Context:")
    assert "What time does school start?" in first_message["content"]


def test_dynamic_context_not_stored_in_history(agent):
    agent.client.beta.messages.create.return_value = _text_response("Test response")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="test_user2")

    stored = agent.redis_store.get_conversation("test_user2")
    assert stored[0]["content"] == "Hello"


def test_dynamic_context_not_prepended_on_subsequent_turns(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("First question", user_id="u3")
        agent.chat("Second question", user_id="u3")

    last_call_messages = agent.client.beta.messages.create.call_args_list[-1][1]["messages"]
    second_user_message = [m for m in last_call_messages if m["role"] == "user"][1]
    assert not second_user_message["content"].startswith("[Context:")


# ── State now lives in the injected RedisStore, not on the agent instance ─────

def test_agent_has_no_instance_state_dicts(agent):
    for attr in ("conversations", "feedback_asked", "feedback_pending",
                 "report_pending", "last_responses", "attach_map"):
        assert not hasattr(agent, attr)


def test_chat_returns_chat_reply(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        reply = agent.chat("Hello", user_id="u4")

    assert isinstance(reply, agent_module.ChatReply)
    assert "Answer" in reply.text
    assert reply.attach_map is False


def test_attach_map_true_when_campus_directions_tool_used(agent):
    tool_use_block = MagicMock(type="tool_use", name="get_campus_directions",
                                input={"destination": "library"}, id="tool_1")
    tool_use_block.name = "get_campus_directions"
    tool_response = MagicMock()
    tool_response.stop_reason = "tool_use"
    tool_response.content = [tool_use_block]

    agent.client.beta.messages.create.side_effect = [tool_response, _text_response("Here's the map")]

    with patch.object(agent, "process_tool_call", return_value=("map info", True)), \
         patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        reply = agent.chat("Where is the library?", user_id="u5")

    assert reply.attach_map is True


# ── No dangling history entry when the API call fails ──────────────────────────

def test_no_dangling_history_entry_on_api_exception(agent):
    agent.client.beta.messages.create.side_effect = Exception("boom")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        # agent.chat now lets upstream failures propagate so the /chat
        # endpoint can return HTTP 500 (proper observability signal).
        with pytest.raises(Exception, match="boom"):
            agent.chat("Hello", user_id="u6")

    # The real invariant this test protects: even when the API call fails,
    # we must not have left a partial user message in the persisted history.
    assert agent.redis_store.get_conversation("u6") == []


# ── Feedback flow routes through the injected RedisStore ───────────────────────

def test_feedback_ask_suffix_added_once_per_session(agent):
    agent.client.beta.messages.create.return_value = _text_response("Answer")

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        first = agent.chat("Hello", user_id="u7")

    assert "Was this helpful?" in first.text
    assert agent.redis_store.is_feedback_asked("u7") is True
    assert agent.redis_store.is_feedback_pending("u7") is True


def test_passive_feedback_reply_records_and_acknowledges(agent):
    agent.redis_store.mark_feedback_pending("u8")

    reply = agent.chat("1", user_id="u8")

    assert "Thanks for the feedback" in reply.text
    assert agent.redis_store.is_feedback_pending("u8") is False
    agent.postgres_store.record_feedback.assert_called_once()
    _, kwargs = agent.postgres_store.record_feedback.call_args
    assert kwargs["sentiment"] == "positive"
    assert kwargs["feedback_type"] == "passive"


def test_report_trigger_requires_prior_response(agent):
    reply = agent.chat("report", user_id="u9")
    assert "no recent response" in reply.text.lower()


def test_report_flow_records_feedback(agent):
    agent.redis_store.set_last_response("u10", "previous answer")
    trigger_reply = agent.chat("report", user_id="u10")
    assert agent.redis_store.is_report_pending("u10") is True

    comment_reply = agent.chat("the phone number was wrong", user_id="u10")

    assert "Thanks for the report" in comment_reply.text
    assert agent.redis_store.is_report_pending("u10") is False
    agent.postgres_store.record_feedback.assert_called_once()
    _, kwargs = agent.postgres_store.record_feedback.call_args
    assert kwargs["feedback_type"] == "report"
    assert kwargs["last_response"] == "previous answer"


def test_system_prompt_instructs_scraped_content_is_untrusted(agent):
    prompt = agent._SYSTEM_PROMPT
    assert "<scraped_page>" in prompt
    assert "untrusted" in prompt.lower()


def test_clear_conversation_clears_redis_session(agent):
    agent.redis_store.append_message("u11", {"role": "user", "content": "hi"})
    agent.redis_store.mark_feedback_asked("u11")

    agent.clear_conversation("u11")

    assert agent.redis_store.get_conversation("u11") == []
    assert agent.redis_store.is_feedback_asked("u11") is False

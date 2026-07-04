"""Unit tests for WellsMiddleSchoolAgent prompt caching changes."""
from unittest.mock import MagicMock, patch, call
import pytest

import app.agent as agent_module
from app.agent import WellsMiddleSchoolAgent


@pytest.fixture()
def agent():
    with patch("app.agent.anthropic.Anthropic"):
        return WellsMiddleSchoolAgent()


# ── Prompt caching: system prompt is static ───────────────────────────────────

def test_system_prompt_template_has_no_today_placeholder(agent):
    assert "{today}" not in agent._system_prompt_template


def test_system_prompt_template_is_stable_across_calls(agent):
    first = agent._system_prompt_template
    second = agent._system_prompt_template
    assert first == second


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
    assert system[0]["text"] == agent._system_prompt_template


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
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text="Test response", type="text")]
    agent.client.beta.messages.create.return_value = mock_response

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
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text="Test response", type="text")]
    agent.client.beta.messages.create.return_value = mock_response

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("Hello", user_id="test_user2")

    stored = agent.conversations["test_user2"]
    assert stored[0]["content"] == "Hello"


def test_dynamic_context_not_prepended_on_subsequent_turns(agent):
    mock_response = MagicMock()
    mock_response.stop_reason = "end_turn"
    mock_response.content = [MagicMock(text="Answer", type="text")]
    agent.client.beta.messages.create.return_value = mock_response

    with patch("app.agent.get_school_day_status", return_value=""), \
         patch("app.agent.get_today_status", return_value=""), \
         patch("app.agent.get_upcoming_events", return_value=""), \
         patch("app.agent.get_upcoming_no_school_days", return_value=""):
        agent.chat("First question", user_id="u3")
        agent.chat("Second question", user_id="u3")

    last_call_messages = agent.client.beta.messages.create.call_args_list[-1][1]["messages"]
    second_user_message = [m for m in last_call_messages if m["role"] == "user"][1]
    assert not second_user_message["content"].startswith("[Context:")

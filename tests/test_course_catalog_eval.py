"""Eval-style regression test for a real production bug: a follow-up
course-catalog question in the same conversation got zero tool calls and a
wrong "I don't have that information" answer — even though the answer was
already sitting in the conversation history from an earlier tool call.
get_course_catalog's overview covers many distinct sub-topics (credits, AP
limits, outside/non-district courses, withdrawal rules, ...), and the model
didn't reliably re-call the tool for a new sub-topic within the same large
result it already had. Calls the *real* Claude API — a mocked client can't
tell us anything about tool-calling reliability across turns.

Skipped unless ANTHROPIC_API_KEY is configured, same as test_language_eval.py.
Run explicitly with a key set:
    ANTHROPIC_API_KEY=sk-... pytest tests/test_course_catalog_eval.py -v
"""
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from app import config
from app.agent import SchoolAgent
from app.schools import get_school
from app.store.redis_store import RedisStore
from tests.store.conftest import FakeRedisClient

pytestmark = pytest.mark.skipif(
    not config.ANTHROPIC_API_KEY,
    reason="requires a real ANTHROPIC_API_KEY to call the live Claude API",
)


@pytest.fixture()
def dhs_agent():
    with patch("app.agent.anthropic.Anthropic"):
        agent = SchoolAgent(
            school=get_school("dhs"),
            redis_store=RedisStore(client=FakeRedisClient()),
            postgres_store=MagicMock(),
        )
    agent.client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return agent


def test_followup_course_catalog_question_re_calls_the_tool(dhs_agent):
    """Asking about graduation credits (fetches the catalog overview), then
    asking an unrelated follow-up about taking courses outside the district
    (a different sub-topic within that same overview) must still call
    get_course_catalog again rather than answering — incorrectly — from
    memory of the earlier large tool result."""
    calls = []
    orig = dhs_agent.process_tool_call

    def spy(name, tool_input):
        calls.append(name)
        return orig(name, tool_input)

    dhs_agent.process_tool_call = spy

    dhs_agent.chat("how many credits do I need to graduate", user_id="eval_catalog_followup")
    calls.clear()
    reply = dhs_agent.chat("can I take a course outside of DUSD", user_id="eval_catalog_followup")

    assert "get_course_catalog" in calls
    assert "don't have" not in reply.text.lower()
    assert "non-district" in reply.text.lower() or "intent form" in reply.text.lower()

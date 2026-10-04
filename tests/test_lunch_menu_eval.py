"""Eval-style regression test for a real production failure: asked "do they
offer bean and cheese quasadilla", the assistant answered WITHOUT calling
get_lunch_menu at all — then hedged that it had no "complete list of all
items the cafeteria offers" and speculated about a la carte options, for a
dish that is plainly on the menu (DHS Friday, allergens milk/soy/wheat).
Its reply carried no source line, which is the tell: no tool call happened.

Same failure class as test_course_catalog_eval.py — zero tool calls and a
confident "I don't have that information" — and like that one it cannot be
caught with a mocked client, because the mock IS the thing that decides
whether a tool gets called. Calls the real Claude API.

The failure is intermittent: the original transcript failed on the dish
availability question while the very next question in the same session
(correctly spelled, same tool) succeeded. So these assert on a PASS RATE
over repeated runs rather than one-shotting, the same way
test_language_eval.py scores a batch instead of a single question. A
single green run proves nothing here.

Skipped unless ANTHROPIC_API_KEY is configured, same as the other evals.
Run explicitly with a key set:
    ANTHROPIC_API_KEY=sk-... pytest tests/test_lunch_menu_eval.py -v
"""
import os
from unittest.mock import MagicMock, patch

import anthropic
import pytest

from app import config
from app.agent import SchoolAgent
from app.schools import get_school
from app.services.lunch_menu import get_lunch_menu_text
from app.store.redis_store import RedisStore
from tests.store.conftest import FakeRedisClient

pytestmark = pytest.mark.skipif(
    not config.ANTHROPIC_API_KEY,
    reason="requires a real ANTHROPIC_API_KEY to call the live Claude API",
)

# How many times each prompt is run. Deliberately small by default — each
# run is a billed, multi-second API call — so a normal invocation catches a
# badly regressed prompt rather than a one-in-fifty flake. Raise it when
# measuring a change whose effect looks marginal; the failure this file
# exists for showed up at roughly 1 run in 3, so 3 is the floor at which
# it's visible at all and a prompt change needs more than that to call:
#     LUNCH_EVAL_RUNS=10 pytest tests/test_lunch_menu_eval.py
#
# Every run must pass. These assert on allergen and availability facts a
# family acts on, so there's no tolerable failure rate to budget for — the
# threshold exists to make a regression legible, not to permit one.
RUNS = int(os.environ.get("LUNCH_EVAL_RUNS", "3"))
REQUIRED = RUNS

# Phrasings a parent actually uses to ask whether a dish exists, including
# the misspelling from the original transcript. None of these name a day,
# which is what made the model treat it as general knowledge rather than a
# menu lookup.
AVAILABILITY_PROMPTS = [
    "do they offer bean and cheese quasadilla",
    "do they offer bean and cheese quesadilla",
    "is bean cheese quesadilla ever on the menu",
    "do they have quesadillas",
]

# Hedges that are ALWAYS wrong for a menu question: the tool is the only
# menu source, so claiming an incomplete view of it — or inventing
# off-menu explanations for an absence — means the model either skipped the
# tool or disbelieved it.
FORBIDDEN_HEDGES = [
    "complete list",
    "may not include everything",
    "à la carte",
    "a la carte",
    "not listed on the public menu",
]


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


def _ask(agent, message, user_id):
    """Sends one message, returning (reply text, tool names called)."""
    calls = []
    original = agent.process_tool_call

    def spy(name, tool_input):
        calls.append(name)
        return original(name, tool_input)

    agent.process_tool_call = spy
    try:
        reply = agent.chat(message, user_id=user_id)
    finally:
        agent.process_tool_call = original
    return reply.text, calls


def test_the_dish_this_eval_is_about_is_actually_on_the_menu():
    """Guard on the fixture, not the model: if the district's next cycle
    drops this dish, every assertion below becomes meaningless and should
    fail here with a clear reason rather than looking like a model
    regression."""
    menu = get_lunch_menu_text("dusd", "9-12")
    assert "Bean Cheese Quesadilla" in menu, (
        "this eval's premise is gone — update it for the current cycle's dishes"
    )


@pytest.mark.parametrize("prompt", AVAILABILITY_PROMPTS)
def test_dish_availability_question_always_calls_the_menu_tool(dhs_agent, prompt):
    """The core regression. A yes/no "do they offer X" is a menu lookup, and
    answering it from general knowledge is how a real dish got reported as
    unavailable."""
    missed = []
    for run in range(RUNS):
        _, calls = _ask(dhs_agent, prompt, user_id=f"eval_lunch_avail_{run}")
        if "get_lunch_menu" not in calls:
            missed.append(run)

    passed = RUNS - len(missed)
    assert passed >= REQUIRED, (
        f"{prompt!r}: get_lunch_menu not called on {len(missed)}/{RUNS} runs "
        f"(runs {missed}) — the model answered a menu question without the menu"
    )


def test_dish_on_the_menu_is_confirmed_with_its_allergens(dhs_agent):
    """The user-visible half: having called the tool, the model must find
    the dish despite the misspelling and quote its allergen list, rather
    than reporting it unavailable."""
    failures = []
    for run in range(RUNS):
        text, _ = _ask(
            dhs_agent,
            "do they offer bean and cheese quasadilla",
            user_id=f"eval_lunch_confirm_{run}",
        )
        lowered = text.lower()
        if "quesadilla" not in lowered:
            failures.append((run, "never named the dish"))
        elif not all(a in lowered for a in ("milk", "soy", "wheat")):
            failures.append((run, "omitted its allergen list"))
        elif hedge := next((h for h in FORBIDDEN_HEDGES if h in lowered), None):
            failures.append((run, f"hedged: {hedge!r}"))

    passed = RUNS - len(failures)
    assert passed >= REQUIRED, f"{len(failures)}/{RUNS} runs wrong: {failures}"


def test_dish_availability_survives_an_earlier_turn_about_one_day(dhs_agent):
    """The actual shape of the production transcript, which single-turn
    probes all pass. The session had already discussed ONE day's menu, and
    the model then answered the availability question from that narrower
    context — reporting a real Friday dish as not on the menu, and once it
    had said so it repeated the claim on the follow-up rather than
    re-reading the tool result. Anchoring on its own prior answer, not a
    cold-start tool-call miss."""
    failures = []
    for run in range(RUNS):
        user_id = f"eval_lunch_anchor_{run}"
        _ask(dhs_agent, "what is for lunch on Monday", user_id=user_id)
        text, calls = _ask(
            dhs_agent, "do they offer bean and cheese quasadilla", user_id=user_id)

        lowered = text.lower()
        # Assert the FACTS a correct answer must carry — the dish's real day
        # and its allergens — rather than scanning for negative phrasing.
        # Searching for "not on"/"don't" flagged two perfectly good replies
        # ("offered on Friday ... not on the Monday menu") as denials, which
        # would have made this eval fail on correct behaviour.
        if "get_lunch_menu" not in calls:
            failures.append((run, "no tool call on the follow-up"))
        elif "friday" not in lowered:
            failures.append((run, f"did not place the dish on Friday: {text[:140]!r}"))
        elif not all(a in lowered for a in ("milk", "soy", "wheat")):
            failures.append((run, f"omitted its allergen list: {text[:140]!r}"))
        elif hedge := next((h for h in FORBIDDEN_HEDGES if h in lowered), None):
            failures.append((run, f"hedged: {hedge!r}"))

    passed = RUNS - len(failures)
    assert passed >= REQUIRED, f"{len(failures)}/{RUNS} runs wrong: {failures}"


def test_a_weekday_dish_is_not_described_as_served_daily(dhs_agent):
    """From the same transcript: a Monday-only dish was described as
    repeating "each day this menu cycle". Each dish sits under ONE weekday;
    saying otherwise sends a family to school on the wrong day."""
    failures = []
    for run in range(RUNS):
        text, _ = _ask(
            dhs_agent,
            "how often do they serve the miso drumstick chicken",
            user_id=f"eval_lunch_weekday_{run}",
        )
        lowered = text.lower()
        if "monday" not in lowered:
            failures.append((run, "did not say Monday"))
        elif any(p in lowered for p in ("each day", "every day", "daily")):
            failures.append((run, "described a Monday dish as daily"))

    passed = RUNS - len(failures)
    assert passed >= REQUIRED, f"{len(failures)}/{RUNS} runs wrong: {failures}"

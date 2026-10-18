"""Unit tests for RedisStore (app/store/redis_store.py)."""
import pytest

from app.store.redis_store import CONV_TTL_SECONDS, MAX_HISTORY, RedisStore, _msgcount_key
from tests.store.conftest import FakeRedisClient


@pytest.fixture()
def redis_store():
    return RedisStore(client=FakeRedisClient())


# ── TTL (#51: conversations persist 5d, refreshed on every append) ─────────

def test_conv_ttl_is_5_days():
    assert CONV_TTL_SECONDS == 5 * 24 * 60 * 60


# ── conversation history ────────────────────────────────────────────────────

def test_get_conversation_empty_by_default(redis_store):
    assert redis_store.get_conversation("u1") == []


def test_append_message_persists_and_orders(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "hi"})
    redis_store.append_message("u1", {"role": "assistant", "content": "hello"})
    assert redis_store.get_conversation("u1") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_append_message_trims_to_max_history(redis_store):
    overflow = 5
    for i in range(MAX_HISTORY + overflow):
        redis_store.append_message("u1", {"role": "user", "content": str(i)})
    history = redis_store.get_conversation("u1")
    assert len(history) == MAX_HISTORY
    assert history[0]["content"] == str(overflow)
    assert history[-1]["content"] == str(MAX_HISTORY + overflow - 1)


def test_conversation_is_per_session(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "a"})
    assert redis_store.get_conversation("u2") == []


def test_clear_conversation(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "a"})
    redis_store.clear_conversation("u1")
    assert redis_store.get_conversation("u1") == []


# ── conversation truncation flag ─────────────────────────────────────────────

def test_conversation_was_truncated_false_when_never_appended(redis_store):
    assert redis_store.conversation_was_truncated("u1") is False


def test_conversation_was_truncated_false_under_max_history(redis_store):
    for i in range(MAX_HISTORY):
        redis_store.append_message("u1", {"role": "user", "content": str(i)})
    assert redis_store.conversation_was_truncated("u1") is False


def test_conversation_was_truncated_true_once_over_max_history(redis_store):
    for i in range(MAX_HISTORY + 1):
        redis_store.append_message("u1", {"role": "user", "content": str(i)})
    assert redis_store.conversation_was_truncated("u1") is True


def test_conversation_was_truncated_is_per_session(redis_store):
    for i in range(MAX_HISTORY + 1):
        redis_store.append_message("u1", {"role": "user", "content": str(i)})
    assert redis_store.conversation_was_truncated("u2") is False


def test_clear_session_resets_truncation_flag(redis_store):
    for i in range(MAX_HISTORY + 1):
        redis_store.append_message("u1", {"role": "user", "content": str(i)})
    redis_store.clear_session("u1")
    assert redis_store.conversation_was_truncated("u1") is False


# ── last response ────────────────────────────────────────────────────────────

def test_last_response_get_default_none(redis_store):
    assert redis_store.get_last_response("u1") is None


def test_last_response_set_and_get(redis_store):
    redis_store.set_last_response("u1", "the answer")
    assert redis_store.get_last_response("u1") == "the answer"


def test_last_response_clear(redis_store):
    redis_store.set_last_response("u1", "the answer")
    redis_store.clear_last_response("u1")
    assert redis_store.get_last_response("u1") is None


# ── flags: feedback_asked / feedback_pending ────────────────────────────────

@pytest.mark.parametrize("is_fn,mark_fn,clear_fn", [
    ("is_feedback_asked", "mark_feedback_asked", "clear_feedback_asked"),
    ("is_feedback_pending", "mark_feedback_pending", "clear_feedback_pending"),
])
def test_flag_lifecycle(redis_store, is_fn, mark_fn, clear_fn):
    is_set = getattr(redis_store, is_fn)
    mark = getattr(redis_store, mark_fn)
    clear = getattr(redis_store, clear_fn)

    assert is_set("u1") is False
    mark("u1")
    assert is_set("u1") is True
    clear("u1")
    assert is_set("u1") is False


def test_flags_are_per_session(redis_store):
    redis_store.mark_feedback_pending("u1")
    assert redis_store.is_feedback_pending("u2") is False


# ── preferred language (#62) ────────────────────────────────────────────────

def test_preferred_language_get_default_none(redis_store):
    assert redis_store.get_preferred_language("u1") is None


def test_preferred_language_set_and_get(redis_store):
    redis_store.set_preferred_language("u1", "es")
    assert redis_store.get_preferred_language("u1") == "es"


def test_preferred_language_is_per_session(redis_store):
    redis_store.set_preferred_language("u1", "zh")
    assert redis_store.get_preferred_language("u2") is None


# ── clear_session ────────────────────────────────────────────────────────────

def test_clear_session_removes_everything(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "hi"})
    redis_store.set_last_response("u1", "answer")
    redis_store.mark_feedback_asked("u1")
    redis_store.mark_feedback_pending("u1")

    redis_store.clear_session("u1")

    assert redis_store.get_conversation("u1") == []
    assert redis_store.get_last_response("u1") is None
    assert redis_store.is_feedback_asked("u1") is False
    assert redis_store.is_feedback_pending("u1") is False


# ── daily message cap (#71) ──────────────────────────────────────────────────

def test_increment_daily_message_count_starts_at_one(redis_store):
    assert redis_store.increment_daily_message_count("u1", "2026-01-01", 3600) == 1


def test_increment_daily_message_count_increments_on_repeated_calls(redis_store):
    redis_store.increment_daily_message_count("u1", "2026-01-01", 3600)
    redis_store.increment_daily_message_count("u1", "2026-01-01", 3600)
    assert redis_store.increment_daily_message_count("u1", "2026-01-01", 3600) == 3


def test_increment_daily_message_count_sets_ttl_only_on_first_call(redis_store):
    """TTL should be pinned to end-of-day-Pacific from the first message of
    the day, not pushed forward on every subsequent message."""
    redis_store.increment_daily_message_count("u1", "2026-01-01", 3600)
    redis_store.increment_daily_message_count("u1", "2026-01-01", 999)
    assert redis_store.client.ttl(_msgcount_key("u1", "2026-01-01")) == 3600


def test_daily_message_count_is_per_user(redis_store):
    redis_store.increment_daily_message_count("u1", "2026-01-01", 3600)
    assert redis_store.get_daily_message_count("u2", "2026-01-01") == 0


def test_daily_message_count_is_per_day(redis_store):
    redis_store.increment_daily_message_count("u1", "2026-01-01", 3600)
    assert redis_store.get_daily_message_count("u1", "2026-01-02") == 0


def test_get_daily_message_count_default_zero(redis_store):
    assert redis_store.get_daily_message_count("u1", "2026-01-01") == 0


def test_get_daily_message_count_reflects_increments(redis_store):
    redis_store.increment_daily_message_count("u1", "2026-01-01", 3600)
    redis_store.increment_daily_message_count("u1", "2026-01-01", 3600)
    assert redis_store.get_daily_message_count("u1", "2026-01-01") == 2


def test_clear_session_does_not_remove_preferred_language(redis_store):
    """Language is a persistent user preference, not conversation content —
    a 'clear' should not silently switch a Spanish-speaking parent's chatbot
    back to English."""
    redis_store.set_preferred_language("u1", "es")

    redis_store.clear_session("u1")

    assert redis_store.get_preferred_language("u1") == "es"


# ── trimming must not orphan a tool_result (#161) ─────────────────────────

@pytest.mark.parametrize("extra", [10, 11])
def test_trimming_never_leaves_a_leading_tool_result(redis_store, extra):
    """History now holds tool_use/tool_result pairs, and the API rejects a
    tool_result whose tool_use isn't present. Slicing to the last MAX_HISTORY
    messages can cut between them — which would 400 every request for the
    rest of that session, long after the turn that caused it.

    Both parities are exercised on purpose: whether the cut orphans a result
    depends on whether the first retained index is odd, so a single total
    silently tests nothing half the time. With extra=10 the slice lands on a
    tool_use and the guard is a no-op; with extra=11 it lands on a
    tool_result and the guard is what saves the session.
    """
    from app.store.redis_store import MAX_HISTORY

    for i in range(MAX_HISTORY + extra):
        if i % 2 == 0:
            redis_store.append_message("s1", {"role": "assistant", "content": [
                {"type": "tool_use", "id": f"t{i}", "name": "x", "input": {}}]})
        else:
            redis_store.append_message("s1", {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"t{i-1}", "content": "data"}]})

    first = redis_store.get_conversation("s1")[0]
    is_tool_result = (
        first.get("role") == "user"
        and isinstance(first.get("content"), list)
        and any(b.get("type") == "tool_result" for b in first["content"]))

    assert not is_tool_result, f"history starts with an orphaned tool_result (extra={extra})"


def test_trimming_keeps_plain_messages_untouched(redis_store):
    """The orphan check must not eat ordinary conversation."""
    from app.store.redis_store import MAX_HISTORY

    for i in range(MAX_HISTORY + 4):
        redis_store.append_message("s2", {"role": "user", "content": f"m{i}"})

    history = redis_store.get_conversation("s2")

    assert len(history) == MAX_HISTORY
    assert history[0]["content"] == f"m{4}"

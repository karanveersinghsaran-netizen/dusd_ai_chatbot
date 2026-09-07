"""Unit tests for RedisStore (app/store/redis_store.py)."""
import pytest

from app.store.redis_store import RedisStore, _msgcount_key
from tests.store.conftest import FakeRedisClient


@pytest.fixture()
def redis_store():
    return RedisStore(client=FakeRedisClient())


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
    for i in range(25):
        redis_store.append_message("u1", {"role": "user", "content": str(i)})
    history = redis_store.get_conversation("u1")
    assert len(history) == 20
    assert history[0]["content"] == "5"
    assert history[-1]["content"] == "24"


def test_conversation_is_per_session(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "a"})
    assert redis_store.get_conversation("u2") == []


def test_clear_conversation(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "a"})
    redis_store.clear_conversation("u1")
    assert redis_store.get_conversation("u1") == []


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

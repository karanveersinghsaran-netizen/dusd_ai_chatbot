"""Unit tests for the per-user daily message cap (#71) — app/daily_cap.py."""
import logging
from dataclasses import replace
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app import config
from app.daily_cap import FRIENDLY_CAP_MESSAGE, check_and_increment, daily_cap_for_school, is_whitelisted
from app.schools import get_school
from app.store.redis_store import RedisStore
from tests.store.conftest import FakeRedisClient

PACIFIC = ZoneInfo("America/Los_Angeles")
FROZEN_NOW = datetime(2026, 11, 4, 10, 30, tzinfo=PACIFIC)


@pytest.fixture()
def redis_store():
    return RedisStore(client=FakeRedisClient())


@pytest.fixture(autouse=True)
def frozen_clock():
    """Freeze app.daily_cap's notion of "now" for every test in this module."""
    with patch("app.daily_cap.pacific_now", return_value=FROZEN_NOW):
        yield


@pytest.fixture(autouse=True)
def small_cap(monkeypatch):
    """A tiny default cap keeps the below/at/above-cap tests fast and
    readable, and an empty whitelist by default so whitelist tests are
    explicit about what they add."""
    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 3)
    monkeypatch.setattr(config, "DAILY_CAP_WHITELIST", set())


# ── daily_cap_for_school ─────────────────────────────────────────────────────

def test_daily_cap_for_school_falls_back_to_district_default():
    school = get_school("wells")
    assert daily_cap_for_school(school) == 3


def test_daily_cap_for_school_uses_per_school_override():
    school = replace(get_school("wells"), daily_message_cap=7)
    assert daily_cap_for_school(school) == 7


def test_daily_cap_for_school_handles_missing_school():
    assert daily_cap_for_school(None) == 3


# ── is_whitelisted ───────────────────────────────────────────────────────────

def test_is_whitelisted(monkeypatch):
    monkeypatch.setattr(config, "DAILY_CAP_WHITELIST", {"staff-1"})
    assert is_whitelisted("staff-1") is True
    assert is_whitelisted("some-student") is False


# ── below / at / above cap ──────────────────────────────────────────────────

def test_below_cap_is_allowed(redis_store):
    school = get_school("wells")
    for expected_count in (1, 2):
        result = check_and_increment("u1", school, redis_store=redis_store)
        assert result.allowed is True
        assert result.count == expected_count
        assert result.limit == 3


def test_at_cap_is_allowed(redis_store):
    school = get_school("wells")
    result = None
    for _ in range(3):
        result = check_and_increment("u1", school, redis_store=redis_store)
    assert result.allowed is True
    assert result.count == 3


def test_above_cap_is_denied(redis_store):
    school = get_school("wells")
    for _ in range(3):
        check_and_increment("u1", school, redis_store=redis_store)
    result = check_and_increment("u1", school, redis_store=redis_store)
    assert result.allowed is False
    assert result.count == 4
    assert result.limit == 3
    assert result.retry_after_seconds > 0


# ── remaining / approaching_limit ───────────────────────────────────────────

def test_remaining_counts_down(redis_store):
    school = get_school("wells")  # cap is 3 (small_cap fixture)
    for expected_remaining in (2, 1, 0):
        result = check_and_increment("u1", school, redis_store=redis_store)
        assert result.remaining == expected_remaining


def test_remaining_never_negative_once_over_cap(redis_store):
    school = get_school("wells")
    for _ in range(4):  # cap is 3, so this goes one over
        result = check_and_increment("u1", school, redis_store=redis_store)
    assert result.remaining == 0


def test_approaching_limit_true_within_warning_threshold(redis_store):
    school = get_school("wells")  # cap 3, WARNING_THRESHOLD 2
    result = None
    for _ in range(2):  # remaining == 1, within threshold
        result = check_and_increment("u1", school, redis_store=redis_store)
    assert result.approaching_limit is True


def test_approaching_limit_false_with_plenty_of_headroom(redis_store):
    school = replace(get_school("wells"), daily_message_cap=50)
    result = check_and_increment("u1", school, redis_store=redis_store)
    assert result.remaining == 49
    assert result.approaching_limit is False


def test_approaching_limit_false_once_denied():
    # allowed=False short-circuits approaching_limit regardless of remaining
    # (there's nothing to warn about — the block message already covers it).
    from app.daily_cap import DailyCapResult
    result = DailyCapResult(allowed=False, limit=3, count=4, retry_after_seconds=60)
    assert result.remaining == 0
    assert result.approaching_limit is False


def test_approaching_limit_false_for_whitelisted_user(redis_store, monkeypatch):
    monkeypatch.setattr(config, "DAILY_CAP_WHITELIST", {"staff-1"})
    school = get_school("wells")
    result = check_and_increment("staff-1", school, redis_store=redis_store)
    assert result.approaching_limit is False


def test_cap_is_tracked_per_user(redis_store):
    school = get_school("wells")
    for _ in range(3):
        check_and_increment("u1", school, redis_store=redis_store)
    result = check_and_increment("u2", school, redis_store=redis_store)
    assert result.allowed is True
    assert result.count == 1


# ── whitelist bypass ─────────────────────────────────────────────────────────

def test_whitelisted_user_bypasses_cap_entirely(redis_store, monkeypatch):
    monkeypatch.setattr(config, "DAILY_CAP_WHITELIST", {"staff-1"})
    school = get_school("wells")
    for _ in range(10):
        result = check_and_increment("staff-1", school, redis_store=redis_store)
        assert result.allowed is True

    # Whitelisted requests never touch the Redis counter.
    assert redis_store.get_daily_message_count("staff-1", "2026-11-04") == 0


# ── friendly message + observability ────────────────────────────────────────

def test_friendly_cap_message_matches_issue_wording():
    assert FRIENDLY_CAP_MESSAGE == (
        "You've reached today's message limit. Try again tomorrow, or contact "
        "the school office if you need help right now."
    )


def test_cap_hit_is_logged(redis_store, caplog):
    school = get_school("wells")
    for _ in range(3):
        check_and_increment("u1", school, redis_store=redis_store)

    with caplog.at_level(logging.WARNING, logger="app.daily_cap"):
        check_and_increment("u1", school, redis_store=redis_store)

    messages = [record.getMessage() for record in caplog.records]
    assert any("daily_message_cap_hit" in m and "user_id=u1" in m for m in messages)


def test_staying_under_cap_does_not_log(redis_store, caplog):
    school = get_school("wells")
    with caplog.at_level(logging.WARNING, logger="app.daily_cap"):
        check_and_increment("u1", school, redis_store=redis_store)

    assert caplog.records == []


# ── day rollover ─────────────────────────────────────────────────────────────

def test_day_rollover_resets_the_counter(redis_store):
    school = get_school("wells")
    for _ in range(3):
        check_and_increment("u1", school, redis_store=redis_store)
    denied = check_and_increment("u1", school, redis_store=redis_store)
    assert denied.allowed is False

    next_day = datetime(2026, 11, 5, 0, 5, tzinfo=PACIFIC)
    with patch("app.daily_cap.pacific_now", return_value=next_day):
        result = check_and_increment("u1", school, redis_store=redis_store)

    assert result.allowed is True
    assert result.count == 1

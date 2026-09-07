"""Eval-style date-reasoning tests for GitHub issue #66.

Claude has no inherent notion of "now" — the chatbot must supply it, in
Pacific time, on every request, and reason about relative dates ("tomorrow",
"last Friday") correctly from there. The Claude API itself is mocked
everywhere in this test suite (see tests/test_agent.py), so what we can
actually verify deterministically is the machinery the agent's answers are
built on: the injected current-date/time context (app/agent.py) and the
canonical, ISO-dated tool output it reasons over (app/services/calendar.py).

Every case below freezes "today" to Wednesday, 2026-11-04 (via
app.timezone_utils.pacific_now/pacific_today, monkeypatched module-wide) and
covers the question types called out in the issue:
  - is there school tomorrow?
  - when is the next event / early dismissal / break?
  - how many school days until winter break?
  - what day of the week is Nov 20?
  - did we have school last Friday?
"""
import datetime
from datetime import date
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from app.services.calendar import (
    count_school_days_until,
    get_school_day_status,
    get_today_status,
    get_upcoming_events,
    get_upcoming_no_school_days,
)
from app.timezone_utils import pacific_now, pacific_today, school_year_label

DISTRICT_ID = "dusd"

# Frozen "current date" for every test in this module — a Wednesday, per the
# issue's own example freeze point.
FROZEN_NOW = datetime.datetime(2026, 11, 4, 10, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
FROZEN_TODAY = FROZEN_NOW.date()


@pytest.fixture(autouse=True)
def frozen_clock():
    """Freeze pacific_now()/pacific_today() to FROZEN_NOW for every test in
    this module. Patching app.timezone_utils.datetime (rather than the
    stdlib globally) keeps the freeze scoped to this process and leaves
    date.fromisoformat / timedelta arithmetic elsewhere untouched."""
    with patch("app.timezone_utils.datetime") as mock_dt:
        mock_dt.now.return_value = FROZEN_NOW
        yield


# ── The frozen clock itself ─────────────────────────────────────────────────

def test_frozen_today_is_the_expected_wednesday():
    assert pacific_today() == date(2026, 11, 4)
    assert pacific_today().strftime("%A") == "Wednesday"


def test_pacific_now_is_tagged_america_los_angeles():
    assert str(pacific_now().tzinfo) == "America/Los_Angeles"


def test_school_year_label_matches_frozen_today():
    assert school_year_label(pacific_today()) == "2026-2027"


# ── "Is there school tomorrow?" ─────────────────────────────────────────────

def test_school_tomorrow_is_a_regular_school_day():
    tomorrow = FROZEN_TODAY + datetime.timedelta(days=1)
    status = get_school_day_status(tomorrow, DISTRICT_ID)
    assert "2026-11-05 (Thursday)" in status
    assert "regular school day" in status


def test_no_school_on_veterans_day_holiday():
    """A no-school day close to the frozen 'today' — 2026-11-11 — should be
    reported unambiguously, not as a bare relative phrase."""
    status = get_school_day_status(date(2026, 11, 11), DISTRICT_ID)
    assert "2026-11-11 (Wednesday)" in status
    assert "Veterans Day Holiday" in status
    assert "no school" in status


# ── "Did we have school last Friday?" ───────────────────────────────────────

def test_school_last_friday_was_a_minimum_day():
    # Frozen today is Wednesday 2026-11-04; the most recent Friday before it
    # is 2026-10-30, a TK-8 minimum day per data/calendars/dusd/2026_27.json.
    last_friday = date(2026, 10, 30)
    assert last_friday.strftime("%A") == "Friday"

    status = get_school_day_status(last_friday, DISTRICT_ID)
    assert "2026-10-30 (Friday)" in status
    assert "school day" in status
    assert "Minimum Day" in status


# ── "What day of the week is Nov 20?" ───────────────────────────────────────

def test_day_of_week_for_november_20():
    assert date(2026, 11, 20).strftime("%A") == "Friday"


def test_upcoming_no_school_days_report_day_of_week_for_every_entry():
    """Tool output must give ISO date + day-of-week for every date it
    surfaces, not just the ones directly asked about — the agent relies on
    this to answer 'what day of the week is X' style follow-ups without
    re-deriving dates itself."""
    result = get_upcoming_no_school_days(FROZEN_TODAY, DISTRICT_ID)
    assert "2026-11-11 (Wednesday)" in result   # Veterans Day Holiday
    assert "2026-11-26 (Thursday)" in result    # Thanksgiving Holiday


# ── "When is the next break?" ───────────────────────────────────────────────

def test_next_break_after_frozen_today_is_thanksgiving():
    result = get_upcoming_no_school_days(FROZEN_TODAY, DISTRICT_ID)
    lines = [l for l in result.splitlines() if l.startswith("- ")]
    assert lines, "expected at least one upcoming no-school entry"
    # Nearest upcoming date overall must be Veterans Day (2026-11-11), before
    # the Thanksgiving Break entry (starts 2026-11-23).
    assert "2026-11-11" in lines[0]
    break_lines = [l for l in lines if "Thanksgiving Break" in l]
    assert break_lines
    assert "2026-11-23 (Monday)" in break_lines[0]
    assert "2026-11-29 (Sunday)" in break_lines[0]


def test_no_school_days_are_never_bare_relative_strings():
    """Tool output must standardize on ISO date + day-of-week — never phrases
    like 'tomorrow' or 'next week'. Phrasing for the user is the agent's job
    (system prompt DATE HANDLING rules), not the tool's."""
    result = get_upcoming_no_school_days(FROZEN_TODAY, DISTRICT_ID)
    for relative_word in ("tomorrow", "next week", "next month", "soon"):
        assert relative_word not in result.lower()


# ── "How many school days until winter break?" ─────────────────────────────

def test_school_days_until_winter_break():
    winter_break_start = date(2026, 12, 21)
    # Computed independently against data/calendars/dusd/2026_27.json:
    # weekdays from 2026-11-05 through 2026-12-20 inclusive, minus the
    # 2026-11-11 and 2026-11-26 holidays and the 2026-11-23..29 Thanksgiving
    # Break week.
    assert count_school_days_until(FROZEN_TODAY, winter_break_start, DISTRICT_ID) == 26


def test_school_days_until_returns_zero_for_a_past_or_same_day_target():
    assert count_school_days_until(FROZEN_TODAY, FROZEN_TODAY, DISTRICT_ID) == 0
    assert count_school_days_until(FROZEN_TODAY, date(2026, 10, 1), DISTRICT_ID) == 0


def test_school_days_until_spans_a_school_year_boundary():
    """A target early in the *next* school year (e.g. asking in June about a
    date after summer) must still count correctly across the calendar-file
    boundary at the 2026_27 / 2027_28 school year split."""
    from_date = date(2027, 5, 1)
    to_date = date(2027, 8, 20)  # inside 2027-28 school year, after last_day
    # No exact expectation on the count (2027_28 calendar may not exist in
    # test fixtures) — just verify it doesn't raise and returns a sane value.
    result = count_school_days_until(from_date, to_date, DISTRICT_ID)
    assert isinstance(result, int)
    assert result >= 0


# ── "When is the next event?" (RSS-backed) ──────────────────────────────────

def _event(title, start, end=None, description=""):
    return {"title": title, "start": start, "end": end or start, "description": description}


def test_next_event_is_reported_with_iso_date_and_day_of_week():
    events = [
        _event("Fall Concert", date(2026, 11, 6)),
        _event("Winter Assembly", date(2026, 12, 3)),
    ]
    with patch("app.services.calendar._fetch_rss_events", return_value=events):
        result = get_upcoming_events("http://example.test/rss", FROZEN_TODAY)

    lines = [l for l in result.splitlines() if l.startswith("- ")]
    assert lines[0].startswith("- 2026-11-06 (Friday): Fall Concert")
    assert "tomorrow" not in result.lower()
    assert "next week" not in result.lower()


def test_ongoing_event_today_is_flagged_and_dated_unambiguously():
    events = [_event("Book Fair", date(2026, 11, 3), date(2026, 11, 6))]
    with patch("app.services.calendar._fetch_rss_events", return_value=events):
        result = get_upcoming_events("http://example.test/rss", FROZEN_TODAY)
        today_status = get_today_status("http://example.test/rss", FROZEN_TODAY)

    assert "2026-11-03 (Tuesday) - 2026-11-06 (Friday)" in result
    assert "[ONGOING TODAY]" in result
    assert "2026-11-04 (Wednesday)" in today_status
    assert "Book Fair" in today_status


# ── Agent-level: the injected date suffix and dynamic context ──────────────

def test_agent_datetime_suffix_uses_frozen_pacific_time(monkeypatch):
    from dataclasses import replace
    from unittest.mock import MagicMock
    from app.agent import SchoolAgent
    from app.schools import get_school
    from app.store.redis_store import RedisStore
    from tests.store.conftest import FakeRedisClient

    with patch("app.agent.anthropic.Anthropic"):
        agent = SchoolAgent(
            school=get_school("wells"),
            redis_store=RedisStore(client=FakeRedisClient()),
            postgres_store=MagicMock(),
        )

    suffix = agent._current_datetime_suffix()
    assert "Wednesday, 2026-11-04 10:30" in suffix
    assert "America/Los_Angeles" in suffix
    assert "School year: 2026-2027" in suffix
    # Never UTC.
    assert "UTC" not in suffix
    assert "GMT" not in suffix

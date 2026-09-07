"""Unit tests for app/timezone_utils.py's seconds_until_pacific_midnight
(#71: TTL for the per-user daily message cap counter).

Deliberately its own module, not folded into tests/test_date_handling.py:
that module's frozen_clock fixture patches app.timezone_utils.datetime
wholesale (an autouse fixture applying to every test in the module), which
would make the datetime(...) constructor call inside
seconds_until_pacific_midnight itself return a MagicMock instead of a real
datetime. These tests call the function directly with an explicit `now`
instead, so no clock-freezing is needed at all.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.timezone_utils import seconds_until_pacific_midnight

PACIFIC = ZoneInfo("America/Los_Angeles")


def test_seconds_until_pacific_midnight_on_an_ordinary_day():
    now = datetime(2026, 11, 4, 22, 0, tzinfo=PACIFIC)
    assert seconds_until_pacific_midnight(now) == 2 * 3600


def test_seconds_until_pacific_midnight_at_exactly_midnight_is_a_full_day():
    now = datetime(2026, 11, 4, 0, 0, tzinfo=PACIFIC)
    assert seconds_until_pacific_midnight(now) == 24 * 3600


def test_seconds_until_pacific_midnight_across_spring_forward():
    """2026-03-08 is the day PDT begins (2:00 AM -> 3:00 AM, clocks skip an
    hour), so that Pacific calendar day is only 23 hours long. From 01:30
    that morning to the following midnight is 21.5 wall-clock hours, not the
    22.5 a naive same-tzinfo subtraction would produce (see the docstring on
    seconds_until_pacific_midnight for why that naive path is wrong)."""
    now = datetime(2026, 3, 8, 1, 30, tzinfo=PACIFIC)
    assert seconds_until_pacific_midnight(now) == int(21.5 * 3600)


def test_seconds_until_pacific_midnight_across_fall_back():
    """2026-11-01 is the day PDT ends (2:00 AM -> 1:00 AM, clocks repeat an
    hour), so that Pacific calendar day is 25 hours long. From 01:30 that
    morning (the first, PDT occurrence — fold=0) to the following midnight
    is 23.5 wall-clock hours."""
    now = datetime(2026, 11, 1, 1, 30, tzinfo=PACIFIC)
    assert seconds_until_pacific_midnight(now) == int(23.5 * 3600)

"""Shared Pacific-timezone helpers.

Dublin USD operates on Pacific time, but the server may run in UTC (or any
other timezone). Claude also has no inherent notion of "now" — it must be
told, every request. Every user-facing "today"/"now" computation in this
codebase should go through here so:
  - DST transitions are handled correctly (via zoneinfo, not a fixed offset)
  - the server's own timezone never leaks into date logic
  - "today" means the same thing everywhere (agent context, calendar tools)
"""
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_now() -> datetime:
    """Current date/time in Pacific — the single source of truth for "now"."""
    return datetime.now(PACIFIC)


def pacific_today() -> date:
    """Current date in Pacific."""
    return pacific_now().date()


def seconds_until_pacific_midnight(now: datetime) -> int:
    """Seconds remaining from `now` (a Pacific-aware datetime) until the next
    Pacific midnight. Used to TTL the daily message-cap counter (#71) so it
    expires exactly at local midnight no matter what timezone the server
    itself runs in.

    Deliberately converts both endpoints to UTC before subtracting. Per the
    datetime docs: "If both are aware and have the same tzinfo attribute,
    the common tzinfo attribute is ignored and the base datetimes are
    compared" — i.e. subtracting two datetimes that share the exact same
    tzinfo *object* (as `now` and the constructed midnight below both do,
    via the module-level PACIFIC singleton) silently skips the UTC-offset
    correction and just diffs naive wall-clock fields. That's wrong on the
    two days a year DST changes: e.g. it would compute 22.5h instead of the
    correct 21.5h from 01:30 to the next midnight on the day clocks spring
    forward. Converting to a fixed-offset zone (UTC) first forces the
    correct absolute-time subtraction on every day, DST or not."""
    tomorrow = now.date() + timedelta(days=1)
    next_midnight = datetime(tomorrow.year, tomorrow.month, tomorrow.day, tzinfo=PACIFIC)
    delta = next_midnight.astimezone(timezone.utc) - now.astimezone(timezone.utc)
    return max(1, round(delta.total_seconds()))


def school_year_label(today: date) -> str:
    """School year label for the given date, e.g. '2026-2027'. DUSD's school
    year starts in August — matches the year-key convention used to select
    the instructional-calendar JSON file (app/services/calendar.py)."""
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{start_year + 1}"

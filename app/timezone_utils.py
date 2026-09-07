"""Shared Pacific-timezone helpers.

Dublin USD operates on Pacific time, but the server may run in UTC (or any
other timezone). Claude also has no inherent notion of "now" — it must be
told, every request. Every user-facing "today"/"now" computation in this
codebase should go through here so:
  - DST transitions are handled correctly (via zoneinfo, not a fixed offset)
  - the server's own timezone never leaks into date logic
  - "today" means the same thing everywhere (agent context, calendar tools)
"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def pacific_now() -> datetime:
    """Current date/time in Pacific — the single source of truth for "now"."""
    return datetime.now(PACIFIC)


def pacific_today() -> date:
    """Current date in Pacific."""
    return pacific_now().date()


def school_year_label(today: date) -> str:
    """School year label for the given date, e.g. '2026-2027'. DUSD's school
    year starts in August — matches the year-key convention used to select
    the instructional-calendar JSON file (app/services/calendar.py)."""
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}-{start_year + 1}"

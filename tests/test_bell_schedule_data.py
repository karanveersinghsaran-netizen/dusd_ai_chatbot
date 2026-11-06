"""Regression guard for hardcoded bell_schedule content in data/schools/*/school.json.

Catches two related bugs found in production:

1. A Grady Day date transcribed wrong (10/8 instead of 10/28), silently
   paired with the "Wednesday - Modified Schedule" heading — only caught by
   a parent cross-checking the live DHS bell schedule page.
2. Even after fixing #1, the model kept mis-stating weekdays for the
   further-out Grady Days (guessing "Monday" for dates that are actually
   Wednesday) because it was computing them itself instead of reading a
   given value. The fix was to spell out "Month Day, Year (Weekday)" for
   every Grady Day directly in the source data, per the system prompt's
   DATE HANDLING rule that the model may only state a weekday it was
   actually given — never compute one.

This test guards both: every Grady Day's stated weekday must match what
Python's own date arithmetic computes for that date, and — since Grady Days
are documented as always a modified *Wednesday* schedule — that weekday must
specifically be Wednesday.
"""
import re
from datetime import datetime

from app.schools import get_school


def _parse_grady_days(bell_schedule: str) -> list:
    match = re.search(r"Grady Days:\s*(.+?)\):", bell_schedule)
    assert match, "expected a 'Grady Days: ...):' list in the DHS bell schedule text"
    entries = []
    for part in match.group(1).split("), "):
        part = part.strip().rstrip(")")
        date_str, weekday_label = part.split(" (")
        entries.append((datetime.strptime(date_str, "%B %d, %Y").date(), weekday_label))
    return entries


def test_dhs_grady_days_have_correct_and_matching_weekdays():
    dhs = get_school("dhs")
    entries = _parse_grady_days(dhs.bell_schedule)
    assert len(entries) == 6

    for d, stated_weekday in entries:
        actual_weekday = d.strftime("%A")
        assert stated_weekday == actual_weekday, (
            f"{d.isoformat()} is labeled '{stated_weekday}' but is actually {actual_weekday}"
        )
        assert actual_weekday == "Wednesday", f"{d.isoformat()} is not a Wednesday"


# ── Dated overrides (Veterans Day week 2026) ────────────────────────────────

def test_dhs_veterans_day_week_overrides_cover_monday_through_friday_of_one_week():
    """The agent renders each override's weekday from its ISO date, so what
    matters here is that the dates themselves are right: five consecutive
    weekdays, Monday to Friday, with Veterans Day (a fixed November 11
    holiday) on the Wednesday."""
    dhs = get_school("dhs")
    week = sorted(
        datetime.strptime(o["date"], "%Y-%m-%d").date()
        for o in dhs.bell_schedule_overrides
        if o["date"].startswith("2026-11-")
    )
    assert [d.strftime("%A") for d in week] == [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
    ]
    assert (week[-1] - week[0]).days == 4
    assert week[2].isoformat() == "2026-11-11"


def test_dhs_veterans_day_override_agrees_with_the_district_calendar():
    """Two sources state Nov 11 is off — the DHS override and the DUSD calendar
    (data/calendars/dusd/2026_27.json). They must not drift apart."""
    from datetime import date

    from app.services.calendar import get_school_day_status

    status = get_school_day_status(date(2026, 11, 11), "dusd")
    assert "Veterans Day" in status and "no school" in status

    dhs = get_school("dhs")
    note = next(o["note"] for o in dhs.bell_schedule_overrides if o["date"] == "2026-11-11")
    assert "no school" in note.lower()

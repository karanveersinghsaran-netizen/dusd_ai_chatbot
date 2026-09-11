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

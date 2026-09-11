"""Regression guard for hardcoded bell_schedule content in data/schools/*/school.json.

Catches the class of bug found in production: a Grady Day date transcribed
wrong (10/8 instead of 10/28) silently paired the wrong weekday with the
"Wednesday - Modified Schedule" section, only caught by a parent
cross-checking the live DHS bell schedule page. Grady Days are documented —
both in our data and on the live page — as always falling on a Wednesday,
which is directly verifiable without hitting the network.
"""
import re
from datetime import date

from app.schools import get_school

# DHS's 2026-27 school year runs Aug 2026 - May 2027; Grady Day dates in the
# bell schedule text are bare "M/D" with no year, so months 7-12 belong to
# 2026 and 1-6 to 2027. Update alongside the Grady Days list when the school
# year rolls over.
_MONTH_TO_YEAR = {m: 2026 if m >= 7 else 2027 for m in range(1, 13)}


def _parse_grady_days(bell_schedule: str) -> list:
    match = re.search(r"Grady Days:\s*([\d/,\s]+)\)", bell_schedule)
    assert match, "expected a 'Grady Days: ...)' list in the DHS bell schedule text"
    dates = []
    for part in match.group(1).split(","):
        month, day = (int(x) for x in part.strip().split("/"))
        dates.append(date(_MONTH_TO_YEAR[month], month, day))
    return dates


def test_dhs_grady_days_all_fall_on_a_wednesday():
    dhs = get_school("dhs")
    for d in _parse_grady_days(dhs.bell_schedule):
        assert d.strftime("%A") == "Wednesday", f"{d.isoformat()} is not a Wednesday"

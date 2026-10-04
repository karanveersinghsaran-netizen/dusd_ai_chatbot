"""Lunch menu service — DUSD's breakfast/lunch menu, per grade band, parsed
from the district's published PDFs (see scripts/parse_lunch_menu.py) into
small structured JSON files rather than re-parsing a PDF live on every
request. Same "human re-runs the parser when the district publishes new
data" convention as app/services/course_catalog.py.

Keyed by MENU CYCLE, not by calendar month:
data/lunch_menus/<district_id>/<grade_band>/<cycle start YYYY_MM_DD>.json.
The district publishes on multi-week cycles that straddle month boundaries
— its own nutrition PDFs are titled e.g. "26-27 SY C2 MENU (AUG 31 - OCT
9)" and "C3 MENU (OCT 12 - NOV 20)" — so a month key is the wrong unit and
was an outage waiting to happen: the original month-keyed version went dark
on Oct 1 2026 while the C2 file on disk was still the district's current,
correct menu for eight more school days. Each file carries its own
start_date/end_date and the URLs it was parsed from, and lookup is "which
cycle covers this date", so the data can never drift from the period it
claims to describe.
"""
import json
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple

from app.timezone_utils import pacific_today

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "lunch_menus"

_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# Status of the cycle we ended up serving, relative to the date asked about.
_CURRENT = "current"
_UPCOMING = "upcoming"
_PAST = "past"


def _parse_date(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        return None


def _load_cycles(district_id: str, grade_band: str) -> List[dict]:
    """Every parsed cycle for this grade band, oldest first. Files missing a
    usable start_date/end_date are skipped rather than crashing the tool —
    a malformed hand-committed file should degrade to "no menu", never to a
    500 on an allergy question."""
    directory = DATA_DIR / district_id / grade_band
    if not directory.is_dir():
        return []

    cycles = []
    for path in sorted(directory.glob("*.json")):
        with open(path, "r", encoding="utf-8") as f:
            menu = json.load(f)
        start, end = _parse_date(menu.get("start_date")), _parse_date(menu.get("end_date"))
        if not start or not end:
            continue
        cycles.append({**menu, "_start": start, "_end": end})
    return sorted(cycles, key=lambda c: c["_start"])


def _select_cycle(cycles: List[dict], on_date: date) -> Tuple[Optional[dict], Optional[str]]:
    """The cycle to serve for `on_date`, plus how it relates to that date.

    Preference order matters for the two ways a date can fall outside every
    cycle. A date in a GAP between cycles (the district's cycles don't abut
    — C2 ends Thu Oct 9, C3 starts Mon Oct 12, leaving the weekend
    uncovered) should resolve forward to the cycle about to start, since
    that's what's actually being served next. A date past the last cycle
    means nobody has re-run the parser yet; fall back to the most recent
    cycle and let the caller flag it as possibly out of date, because a
    stale-but-labelled menu is far more useful than the tool silently going
    dark — which is exactly the failure this module's docstring describes."""
    if not cycles:
        return None, None
    for cycle in cycles:
        if cycle["_start"] <= on_date <= cycle["_end"]:
            return cycle, _CURRENT
    upcoming = [c for c in cycles if c["_start"] > on_date]
    if upcoming:
        return upcoming[0], _UPCOMING
    return cycles[-1], _PAST


def _format_dish(dish: dict) -> str:
    allergens = dish.get("allergens") or []
    allergen_text = ", ".join(allergens) if allergens else "none listed"
    return f"- {dish['name']} (allergens: {allergen_text})"


def _format_date(value: date) -> str:
    """'October 12, 2026'. Built by hand rather than with strftime's %-d
    day-without-zero-padding, which is a glibc/BSD extension and not
    portable (notably absent on Windows)."""
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def get_lunch_menu_urls(
    district_id: str, grade_band: str, on_date: Optional[date] = None
) -> Tuple[Optional[str], Optional[str]]:
    """(menu_url, nutrition_url) for the cycle being served — the PDFs this
    cycle's data was actually parsed from. These live in the cycle JSON
    rather than in school.json because they're cycle-specific: a link kept
    on the school record goes stale the moment the district publishes a new
    cycle, and then cites the wrong document for the data being quoted."""
    cycle, _ = _select_cycle(_load_cycles(district_id, grade_band), on_date or pacific_today())
    if not cycle:
        return None, None
    return cycle.get("menu_url"), cycle.get("nutrition_url")


def get_lunch_menu_text(
    district_id: str, grade_band: str, on_date: Optional[date] = None
) -> str:
    """Returns the whole cycle's menu as formatted text — every weekday's
    dish choices plus the always-available daily options, each with its
    listed allergens. No day-of-week filtering here: the whole week is
    compact enough (~15-20 dishes) to return in full and let the model
    reason over it, the same way get_club_list/get_campus_directions return
    curated content rather than a narrower, param-driven slice. A narrower
    param would just be new surface for the "model picks the wrong param
    and misses info" failure class already hit — and fixed — twice for
    get_school_information and get_course_catalog.

    The header states today's date and the cycle's date range explicitly,
    because the model can't otherwise tell whether the weekday pattern it's
    reading applies to the day being asked about."""
    today = on_date or pacific_today()
    cycle, status = _select_cycle(_load_cycles(district_id, grade_band), today)
    if not cycle:
        return "No lunch menu is available for this school right now."

    period = f"{_format_date(cycle['_start'])} through {_format_date(cycle['_end'])}"
    label = cycle.get("period_label")
    lines = [
        f"Today is {_format_date(today)}.",
        f"Menu period: {period}" + (f" ({label})" if label else ""),
    ]
    if status == _UPCOMING:
        lines.append(
            "NOTE: no menu is published for today itself — today falls between menu "
            "periods (typically a weekend or break). This is the NEXT period's menu; "
            "say so, and give its start date, rather than presenting it as today's."
        )
    elif status == _PAST:
        lines.append(
            "NOTE: this period has already ENDED and the district has likely published "
            "a newer menu that isn't loaded here yet. Lead with that caveat, give this "
            "period's end date, and point the user to the menu link for the current "
            "one — do NOT present these dishes as what's being served today."
        )
    if cycle.get("peanut_tree_nut_free"):
        lines.append("District-wide: meals are peanut & tree nut free (except coconut).")
    for note in cycle.get("notes") or []:
        lines.append(f"Note: {note}")

    days = cycle.get("days", {})
    for weekday in _WEEKDAY_ORDER:
        dishes = days.get(weekday)
        if not dishes:
            continue
        lines.append(f"\n{weekday}:")
        lines.extend(_format_dish(d) for d in dishes)

    daily_options = cycle.get("daily_options") or []
    if daily_options:
        lines.append("\nAvailable every day:")
        lines.extend(_format_dish(d) for d in daily_options)

    return "\n".join(lines)

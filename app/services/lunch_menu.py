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


def get_lunch_nutrition_links(
    district_id: str, grade_band: str, on_date: Optional[date] = None
) -> List[Tuple[str, str, str, str]]:
    """(status, period start, period end, nutrition document URL) for the
    period covering `on_date` and, when it's parsed, the one after it. Status
    is _CURRENT or _UPCOMING.

    Exists so the agent can state these documents in its per-request system
    context rather than only inside a tool result. A tool result is discarded
    at the end of the turn that produced it, so a follow-up question — "what
    is the nutrition info", right after a menu answer — reached a model that
    had no idea the document existed, and answered that nutrition data was
    unavailable while we held the district's own figures. Nutrition questions
    are overwhelmingly follow-ups to a menu question, so the tool result is
    the one place this link is least likely to be seen."""
    cycles = _load_cycles(district_id, grade_band)
    selected, status = _select_cycle(cycles, on_date or pacific_today())
    if not selected:
        return []
    # Pass _select_cycle's OWN status through. Hardcoding _CURRENT here told
    # the caller that the served cycle covers today even when it doesn't: on
    # a gap day (today between two cycles) _select_cycle resolves forward, so
    # on Saturday October 10 2026 this claimed the October 12-30 period
    # "covers today". A later period is only appended when today really is
    # inside a cycle — when the status is _UPCOMING the selected cycle is
    # already the next one, and when it is _PAST there is no later cycle.
    periods = [(status, selected)]
    if status == _CURRENT:
        nxt = _next_cycle(cycles, selected)
        if nxt:
            periods.append((_UPCOMING, nxt))
    # Returns the STATUS explicitly rather than relying on list order. Order
    # alone is wrong the moment the current period has no nutrition_url and
    # the next one does — the caller would then label the next period as the
    # current one, which is precisely the mislabelling this signature exists
    # to prevent.
    return [
        (status, _format_date(c["_start"]), _format_date(c["_end"]), c["nutrition_url"])
        for status, c in periods
        if c.get("nutrition_url")
    ]


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
    reading applies to the day being asked about.

    When the NEXT cycle is already parsed, it's appended as a second, clearly
    fenced block (see _render_upcoming_block) so questions about a date just
    past a cycle boundary can be answered. Returning only today's cycle meant
    "what's for lunch on Monday?" asked the week before a boundary was
    declined for data already sitting on disk."""
    today = on_date or pacific_today()
    cycles = _load_cycles(district_id, grade_band)
    cycle, status = _select_cycle(cycles, today)
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
    lines.extend(_render_cycle_body(cycle))

    # When today sits inside a cycle and the NEXT one is already parsed, append
    # it as a clearly-fenced second block. Without this the tool returned only
    # today's cycle, so "what's for lunch on Monday?" asked a few days before a
    # cycle boundary was declined for a menu already sitting on disk — the data
    # was there, the model was just never shown it.
    #
    # Only for _CURRENT: the _UPCOMING branch is already serving the next cycle
    # as its primary block (appending it again would print it twice), and _PAST
    # means there is no later cycle by definition.
    upcoming = _next_cycle(cycles, cycle) if status == _CURRENT else None
    if upcoming:
        lines.extend(_render_upcoming_block(upcoming, cycle))

    return "\n".join(lines)


def _render_cycle_body(cycle: dict, weekday_suffix: str = "") -> List[str]:
    """One cycle's dishes — the part that's identical for the current and the
    upcoming block. weekday_suffix is appended to each weekday heading so a
    reader (human or model) can't mistake which period a "Monday:" belongs to
    once two of them are on screen."""
    lines = []
    if cycle.get("peanut_tree_nut_free"):
        lines.append("District-wide: meals are peanut & tree nut free (except coconut).")
    for note in cycle.get("notes") or []:
        lines.append(f"Note: {note}")

    days = cycle.get("days", {})
    for weekday in _WEEKDAY_ORDER:
        dishes = days.get(weekday)
        if not dishes:
            continue
        lines.append(f"\n{weekday}{weekday_suffix}:")
        lines.extend(_format_dish(d) for d in dishes)

    daily_options = cycle.get("daily_options") or []
    if daily_options:
        lines.append(f"\nAvailable every day{weekday_suffix}:")
        lines.extend(_format_dish(d) for d in daily_options)
    return lines


def _render_upcoming_block(upcoming: dict, current: dict) -> List[str]:
    """The next cycle, fenced and labelled so it can't be read as today's.

    The fencing is deliberately heavy-handed. Two periods means two different
    "Monday" blocks in one result, and this model has already demonstrated it
    will misread this data — describing a Monday-only dish as served "each
    day", and denying a dish that was present in the output. Quoting the wrong
    period's allergens for a date is the specific harm to avoid, so the block
    states its date range, repeats it on every weekday heading, and says
    explicitly which dates each period governs rather than leaving the model to
    infer it from two bare ranges."""
    start, end = _format_date(upcoming["_start"]), _format_date(upcoming["_end"])
    label = upcoming.get("period_label")
    return [
        "",
        "=== NEXT MENU PERIOD — NOT what is being served now ===",
        f"A newer menu period starts {start} and runs through {end}"
        + (f" ({label})." if label else "."),
        f"Use the dishes below ONLY for dates from {start} onward. For any date up to "
        f"and including {_format_date(current['_end'])}, use the menu ABOVE. The two "
        "periods serve DIFFERENT dishes on the same weekday, so decide which period "
        "the date falls in before quoting any dish or allergen list.",
        # The SOURCE line the caller prepends describes the CURRENT period, so
        # an answer about this later one would otherwise cite the wrong
        # document — the exact period/source mismatch that putting URLs on the
        # cycle instead of the school record was meant to prevent. Observed
        # live before this line existed: a reply about October 12 citing the
        # September PDF.
        *([f"Source document for THIS later period: {upcoming['menu_url']} — when your "
           "answer is about dates in this later period, cite this link as the single "
           "📍 Source instead of the SOURCE line above, which describes the current "
           "period only."] if upcoming.get("menu_url") else []),
        # The nutrition document is period-specific too, and the one the agent
        # offers alongside its SOURCE line belongs to the CURRENT period. A
        # nutrition question about a date in this later period would otherwise
        # be answered with the previous period's figures.
        *([f"Nutrition document for THIS later period (per-ingredient calories, sodium, "
           f"saturated fat, carbs, fiber, added sugar): {upcoming['nutrition_url']} — use "
           "this one, not the current period's, for nutrition questions about dates in "
           "this later period."] if upcoming.get("nutrition_url") else []),
        *_render_cycle_body(upcoming, weekday_suffix=f" ({start} onward)"),
    ]


def _next_cycle(cycles: List[dict], current: dict) -> Optional[dict]:
    """The earliest cycle starting after `current` ends, or None."""
    later = [c for c in cycles if c["_start"] > current["_end"]]
    return later[0] if later else None

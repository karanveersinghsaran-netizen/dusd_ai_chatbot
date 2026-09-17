"""Lunch menu service — DUSD's monthly breakfast/lunch menu, per grade band,
parsed from the district's published PDFs (see scripts/parse_lunch_menu.py)
into a small structured JSON file rather than re-parsing a PDF live on every
request. Same file layout and "human re-runs the parser when the district
publishes new data" convention as app/services/course_catalog.py:
data/lunch_menus/<district_id>/<grade_band>/<YYYY_MM>.json.
"""
import json
from pathlib import Path
from typing import Optional

from app.timezone_utils import pacific_today

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "lunch_menus"

_WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _current_month_key() -> str:
    """'YYYY_MM' for the current Pacific-time month — the menu JSON's
    default lookup key when a caller doesn't pin a specific month."""
    today = pacific_today()
    return f"{today.year}_{today.month:02d}"


def _load_menu(district_id: str, grade_band: str, month_key: Optional[str] = None) -> Optional[dict]:
    key = month_key or _current_month_key()
    path = DATA_DIR / district_id / grade_band / f"{key}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _format_dish(dish: dict) -> str:
    allergens = dish.get("allergens") or []
    allergen_text = ", ".join(allergens) if allergens else "none listed"
    return f"- {dish['name']} (allergens: {allergen_text})"


def get_lunch_menu_text(district_id: str, grade_band: str, month_key: Optional[str] = None) -> str:
    """Returns the whole month's menu as formatted text — every weekday's
    dish choices plus the always-available daily options, each with its
    listed allergens. No day-of-week filtering here: the whole week is
    compact enough (~15-20 dishes) to return in full and let the model
    reason over it, the same way get_club_list/get_campus_directions return
    curated content rather than a narrower, param-driven slice. A narrower
    param would just be new surface for the "model picks the wrong param
    and misses info" failure class already hit — and fixed — twice this
    session for get_school_information and get_course_catalog."""
    menu = _load_menu(district_id, grade_band, month_key)
    if not menu:
        return "No lunch menu is available for this school right now."

    lines = [f"Menu period: {menu.get('period_label', 'this month')}"]
    if menu.get("peanut_tree_nut_free"):
        lines.append("District-wide: meals are peanut & tree nut free (except coconut).")

    days = menu.get("days", {})
    for weekday in _WEEKDAY_ORDER:
        dishes = days.get(weekday)
        if not dishes:
            continue
        lines.append(f"\n{weekday}:")
        lines.extend(_format_dish(d) for d in dishes)

    daily_options = menu.get("daily_options") or []
    if daily_options:
        lines.append("\nAvailable every day:")
        lines.extend(_format_dish(d) for d in daily_options)

    return "\n".join(lines)

"""Converts a DUSD grade-band nutrition PDF (per-ingredient allergen table)
plus a hand-written day->dish-name map into the structured JSON
app/services/lunch_menu.py serves. Re-run this whenever the district
publishes a new month's menu.

The nutrition PDF has a real, structured "Allergens List" column — one row
per ingredient/component per dish — extractable via pymupdf's table finder.
It does NOT say which dish is offered on which weekday, though: that's a
separate, visually-laid-out calendar PDF (graphic, not a clean table), so
the day->dish mapping is a small file a human writes by reading that
calendar PDF once a month (same maintenance shape as
parse_course_catalog.py's DEPARTMENT_HEADINGS).

Usage:
    python -m scripts.parse_lunch_menu "path/to/nutrition.pdf" \
        --district-id dusd --grade-band 6-8 \
        --period-label "September 2026" --month-key 2026_09 \
        --day-map path/to/day_map.json \
        --peanut-tree-nut-free \
        --out data/lunch_menus/dusd/6-8/2026_09.json

day_map.json shape:
    {
      "Monday": ["Cheeseburger with Potato Wedges", "Cheesy Breaded Ravioli with Marinara Sauce"],
      "Tuesday": [...], "Wednesday": [...], "Thursday": [...], "Friday": [...],
      "daily_options": ["Spicy Chicken Sandwich", "Grilled Cheese with Tomato Soup", ...],
      "overrides": {"Some Dish Name": ["wheat", "milk"]}
    }

"overrides" is optional — a complete, manually verified replacement of a
dish's extracted allergen set, for the rare case _extract_dish_allergens
can't recover from automatically (see its docstring) or to correct
contamination one of those cases caused in a neighboring dish.
"""
import argparse
import json
from pathlib import Path
from typing import Dict, List, Set

import fitz


_HEADER_ECHO_NAMES = {"Breakfast Menu Item", "Lunch Menu Item", "Menu Item"}


def _clean_cell(value) -> str:
    return " ".join((value or "").split())


def _extract_dish_allergens(pdf_path: Path) -> Dict[str, Set[str]]:
    """Groups every ingredient row into per-dish segments and unions each
    segment's allergens.

    A new segment starts wherever the "Day" column (row[0]) has a value
    (M/TU/W/TH/F/M-F/...) — a rowspan effect flattens it to blank on every
    row after a dish's first. The dish NAME (row[1]) is also usually only
    on that first row — but at a page break, pymupdf sometimes drops the
    name from the row that has the Day value and instead places it on a
    LATER row within the same segment (observed on real DUSD menu PDFs,
    e.g. the actual name only showing up on a "Parsley" or "Apple" row
    several lines into what's otherwise an unnamed segment). So rather than
    require the name on the boundary row, this takes the first non-empty
    name found ANYWHERE in the segment.

    KNOWN LIMITATION: occasionally the FIRST row of a dish's real
    ingredients has neither a Day value nor a name (both blank) — e.g. it
    lands right at a page break with nothing pymupdf could extract for
    either column. Those rows get glued onto whatever segment precedes
    them instead of starting a fresh one, since there's no boundary signal
    to detect at all. Always spot-check the generated JSON's dish list
    against the source PDF before committing it — a dish with an
    implausibly small/empty allergen set, or a neighboring dish with
    allergens that don't match its own ingredients, is the tell. Verified
    and hand-corrected for the initial September 2026 data; see
    scripts/lunch_menu_day_maps/README.md for the specific corrections."""
    segments: List[List[list]] = []
    for page in fitz.open(pdf_path):
        for table in page.find_tables().tables:
            rows = table.extract()
            if not rows or rows[0][0] != "Day":
                continue
            for row in rows[1:]:
                if len(row) < 10:
                    continue
                if _clean_cell(row[1]) in _HEADER_ECHO_NAMES:
                    continue
                if row[0] or not segments:
                    segments.append([])
                segments[-1].append(row)

    dish_allergens: Dict[str, Set[str]] = {}
    for segment in segments:
        name = next((_clean_cell(r[1]) for r in segment if _clean_cell(r[1])), None)
        if not name:
            continue
        bucket = dish_allergens.setdefault(name, set())
        for row in segment:
            for allergen in (row[9] or "").split(","):
                cleaned = allergen.strip().lower()
                if cleaned and cleaned not in ("-", "--", "n/a"):
                    bucket.add(cleaned)

    return dish_allergens


def _resolve(day_map_names: List[str], dish_allergens: Dict[str, Set[str]], overrides: dict) -> List[dict]:
    unmatched = [n for n in day_map_names if n not in dish_allergens and n not in overrides]
    if unmatched:
        raise ValueError(
            f"day-map name(s) not found in extracted nutrition table (and no override given): "
            f"{unmatched}. Available dish names: {sorted(dish_allergens.keys())}"
        )
    return [
        {"name": name, "allergens": sorted(overrides.get(name, dish_allergens.get(name, [])))}
        for name in day_map_names
    ]


def parse(pdf_path: Path, day_map: dict) -> Dict[str, List[dict]]:
    """day_map may include an "overrides" key: {dish_name: [allergen, ...]},
    a COMPLETE replacement of that dish's extracted allergen set — for the
    rare page-break case _extract_dish_allergens can't recover from at all
    (see its docstring), or to correct a set contaminated by one of those
    cases bleeding into a neighboring dish. Always a manually verified,
    documented correction, never a silent guess — see
    scripts/lunch_menu_day_maps/README.md for this month's specific cases
    and how they were verified."""
    dish_allergens = _extract_dish_allergens(pdf_path)
    overrides = day_map.get("overrides", {})

    days = {}
    for weekday in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday"):
        if weekday in day_map:
            days[weekday] = _resolve(day_map[weekday], dish_allergens, overrides)

    result = {"days": days}
    if "daily_options" in day_map:
        result["daily_options"] = _resolve(day_map["daily_options"], dish_allergens, overrides)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("nutrition_pdf", type=Path)
    parser.add_argument("--district-id", required=True, help="e.g. dusd")
    parser.add_argument("--grade-band", required=True, help="e.g. 6-8, 9-12")
    parser.add_argument("--period-label", required=True, help="e.g. 'September 2026'")
    parser.add_argument("--month-key", required=True, help="e.g. 2026_09")
    parser.add_argument("--day-map", type=Path, required=True)
    parser.add_argument("--peanut-tree-nut-free", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    day_map = json.loads(args.day_map.read_text(encoding="utf-8"))
    data = parse(args.nutrition_pdf, day_map)
    data["period_label"] = args.period_label
    data["peanut_tree_nut_free"] = args.peanut_tree_nut_free

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    total_dishes = sum(len(v) for v in data["days"].values()) + len(data.get("daily_options", []))
    print(f"Wrote {args.out} — {len(data['days'])} weekdays, {total_dishes} dishes total")


if __name__ == "__main__":
    main()

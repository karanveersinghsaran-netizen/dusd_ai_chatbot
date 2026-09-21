"""Unit tests for scripts/parse_lunch_menu.py.

_extract_dish_allergens tests use synthetic rows in the exact shapes
pymupdf's find_tables().extract() actually returned for the real DUSD
nutrition PDFs used to build this feature's initial data (verified by hand
against schoolnutritionandfitness.com's September 2026 6-8/9-12 PDFs) —
including the page-break quirk where a dish's name lands on a LATER row
within its segment rather than the first one.
"""
from unittest.mock import MagicMock, patch

import pytest

from scripts.parse_lunch_menu import _extract_dish_allergens, _resolve, parse

HEADER_ROW = [
    "Day", "Breakfast Menu Item", "Item Details", "Cal\n(Kcal)", "Sodium\n(Mg)",
    "Saturated\nFat (g)", "Carbs\n(g)", "Fiber\n(g)", "Added\nSugar (g)", "Allergens List",
]


def _fake_pdf(page_tables):
    """page_tables: list of pages, each a list of tables, each table a list
    of rows (the header row is added automatically per table)."""
    doc = MagicMock()
    pages = []
    for tables in page_tables:
        page = MagicMock()
        table_mocks = []
        for rows in tables:
            table = MagicMock()
            table.extract.return_value = [HEADER_ROW] + rows
            table_mocks.append(table)
        page.find_tables.return_value = MagicMock(tables=table_mocks)
        pages.append(page)
    doc.__iter__ = lambda self: iter(pages)
    return doc


# ── _extract_dish_allergens ─────────────────────────────────────────────────

def test_extract_simple_single_row_dish():
    rows = [["M", "Cheeseburger", "Bun", "160", "-", "-", "-", "-", "-", "wheat, soy"]]
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=_fake_pdf([[rows]])):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {"Cheeseburger": {"wheat", "soy"}}


def test_extract_unions_allergens_across_continuation_rows():
    rows = [
        ["M", "Cheeseburger", "Bun", "-", "-", "-", "-", "-", "-", "wheat, soy"],
        [None, None, "Patty", "-", "-", "-", "-", "-", "-", "milk"],
        [None, None, "Tray", "-", "-", "-", "-", "-", "-", "-"],
    ]
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=_fake_pdf([[rows]])):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {"Cheeseburger": {"wheat", "soy", "milk"}}


def test_extract_filters_dash_and_na_as_no_allergen():
    rows = [
        ["M", "Fruit Cup", "Apple", "-", "-", "-", "-", "-", "-", "--"],
        [None, None, "Mustard", "-", "-", "-", "-", "-", "-", "n/a"],
    ]
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=_fake_pdf([[rows]])):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {"Fruit Cup": set()}


def test_extract_skips_header_echo_rows_without_resetting_current_dish():
    """The header repeats mid-table wherever the source PDF's table spans a
    page break — treating it as a fake dish would orphan whatever real dish
    comes right after it."""
    rows = [
        ["M", "Cheeseburger", "Bun", "-", "-", "-", "-", "-", "-", "wheat"],
        ["Day", "Breakfast Menu Item", "Item Details", "Cal", "Sodium", "Fat", "Carbs", "Fiber", "Sugar", "Allergens List"],
        [None, None, "Patty", "-", "-", "-", "-", "-", "-", "milk"],
    ]
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=_fake_pdf([[rows]])):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {"Cheeseburger": {"wheat", "milk"}}


def test_extract_resolves_name_found_later_in_segment():
    """Reproduces the real page-break quirk: the Day marker is on the first
    row of a new dish, but the dish NAME text didn't extract until a later
    row within the same segment — seen for real on "Grilled Cheese with
    Tomato Soup" in the September 2026 Wells nutrition PDF."""
    rows = [
        ["M-F", "", "Grilled Cheese Sandwich", "-", "-", "-", "-", "-", "-", "wheat, milk, soy"],
        [None, None, "Tomato Soup", "-", "-", "-", "-", "-", "-", "milk"],
        [None, "Grilled Cheese with Tomato Soup", "Parsley", "-", "-", "-", "-", "-", "-", "--"],
    ]
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=_fake_pdf([[rows]])):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {"Grilled Cheese with Tomato Soup": {"wheat", "milk", "soy"}}


def test_extract_normalizes_wrapped_dish_names():
    rows = [["M", "Cheeseburger with\nPotato Wedges", "Bun", "-", "-", "-", "-", "-", "-", "wheat"]]
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=_fake_pdf([[rows]])):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {"Cheeseburger with Potato Wedges": {"wheat"}}


def test_extract_continues_current_dish_across_pages():
    page1 = [["M", "Cheeseburger", "Bun", "-", "-", "-", "-", "-", "-", "wheat"]]
    page2 = [[None, None, "Patty", "-", "-", "-", "-", "-", "-", "milk"]]
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=_fake_pdf([[page1], [page2]])):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {"Cheeseburger": {"wheat", "milk"}}


def test_extract_skips_non_data_tables():
    """A table whose first row isn't the "Day" header (e.g. a page fragment
    that isn't this nutrition table at all) is ignored entirely."""
    unrelated_table = [["Some", "Other", "Table"]]
    doc = MagicMock()
    page = MagicMock()
    table = MagicMock()
    table.extract.return_value = unrelated_table
    page.find_tables.return_value = MagicMock(tables=[table])
    doc.__iter__ = lambda self: iter([page])
    with patch("scripts.parse_lunch_menu.fitz.open", return_value=doc):
        result = _extract_dish_allergens("fake.pdf")
    assert result == {}


# ── _resolve / parse ─────────────────────────────────────────────────────────

DISH_ALLERGENS = {
    "Cheeseburger": {"wheat", "soy"},
    "Veggie Bowl": set(),
}


def test_resolve_builds_sorted_allergen_lists():
    result = _resolve(["Cheeseburger", "Veggie Bowl"], DISH_ALLERGENS, {})
    assert result == [
        {"name": "Cheeseburger", "allergens": ["soy", "wheat"]},
        {"name": "Veggie Bowl", "allergens": []},
    ]


def test_resolve_raises_on_unmatched_name_with_no_override():
    with pytest.raises(ValueError, match="Mystery Dish"):
        _resolve(["Mystery Dish"], DISH_ALLERGENS, {})


def test_resolve_applies_override_for_unmatched_name():
    result = _resolve(["Mystery Dish"], DISH_ALLERGENS, {"Mystery Dish": ["egg"]})
    assert result == [{"name": "Mystery Dish", "allergens": ["egg"]}]


def test_resolve_override_replaces_extracted_set_entirely():
    """An override for a dish that WAS extracted (e.g. to correct
    contamination from a neighboring dish) fully replaces its allergen set,
    not merges with it."""
    result = _resolve(["Cheeseburger"], DISH_ALLERGENS, {"Cheeseburger": ["milk"]})
    assert result == [{"name": "Cheeseburger", "allergens": ["milk"]}]


def test_parse_builds_days_and_daily_options():
    day_map = {
        "Monday": ["Cheeseburger"],
        "Tuesday": ["Veggie Bowl"],
        "daily_options": ["Cheeseburger"],
    }
    with patch("scripts.parse_lunch_menu._extract_dish_allergens", return_value=DISH_ALLERGENS):
        result = parse("fake.pdf", day_map)

    assert result["days"]["Monday"] == [{"name": "Cheeseburger", "allergens": ["soy", "wheat"]}]
    assert result["days"]["Tuesday"] == [{"name": "Veggie Bowl", "allergens": []}]
    assert "Wednesday" not in result["days"]
    assert result["daily_options"] == [{"name": "Cheeseburger", "allergens": ["soy", "wheat"]}]


def test_parse_without_daily_options_key_omits_it():
    day_map = {"Monday": ["Cheeseburger"]}
    with patch("scripts.parse_lunch_menu._extract_dish_allergens", return_value=DISH_ALLERGENS):
        result = parse("fake.pdf", day_map)
    assert "daily_options" not in result

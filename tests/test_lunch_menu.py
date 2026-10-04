"""Unit tests for the lunch menu service (app/services/lunch_menu.py)."""
import json
from datetime import date
from unittest.mock import patch

import pytest

from app.services.lunch_menu import get_lunch_menu_text, get_lunch_menu_urls

# The two cycles below mirror the real DUSD shape that broke the original
# month-keyed version: consecutive multi-week cycles that straddle a month
# boundary and do NOT abut (C2 ends Thu Oct 9, C3 starts Mon Oct 12).
CYCLE_2 = {
    "period_label": "Cycle 2",
    "start_date": "2026-08-31",
    "end_date": "2026-10-09",
    "peanut_tree_nut_free": True,
    "menu_url": "https://example.test/c2_menu.pdf",
    "nutrition_url": "https://example.test/c2_nutrition.pdf",
    "days": {
        "Monday": [
            {"name": "Cheeseburger", "allergens": ["wheat", "milk"]},
            {"name": "Veggie Bowl", "allergens": []},
        ],
        "Tuesday": [{"name": "Taco Tuesday", "allergens": ["wheat", "milk", "soy"]}],
    },
    "daily_options": [{"name": "Sidekick", "allergens": ["soy", "sesame"]}],
}

CYCLE_3 = {
    "period_label": "Cycle 3",
    "start_date": "2026-10-12",
    "end_date": "2026-11-20",
    "peanut_tree_nut_free": True,
    "menu_url": "https://example.test/c3_menu.pdf",
    "nutrition_url": "https://example.test/c3_nutrition.pdf",
    "notes": ["No school October 15-16, 2026 — no meals served."],
    "days": {"Monday": [{"name": "Pulled Pork Sandwich", "allergens": ["soy", "wheat"]}]},
    "daily_options": [],
}


def _write(tmp_path, *cycles, grade_band="6-8"):
    directory = tmp_path / "acme" / grade_band
    directory.mkdir(parents=True, exist_ok=True)
    for index, cycle in enumerate(cycles):
        # Named after the start date in real data; the index keeps the
        # filename valid for the deliberately-malformed fixtures too, since
        # the service reads the range from inside the file, not the name.
        name = (cycle.get("start_date") or f"malformed_{index}").replace("-", "_")
        (directory / f"{name}.json").write_text(json.dumps(cycle))
    return tmp_path


@pytest.fixture()
def menu_dir(tmp_path):
    _write(tmp_path, CYCLE_2)
    with patch("app.services.lunch_menu.DATA_DIR", tmp_path):
        yield tmp_path


@pytest.fixture()
def two_cycle_dir(tmp_path):
    _write(tmp_path, CYCLE_2, CYCLE_3)
    with patch("app.services.lunch_menu.DATA_DIR", tmp_path):
        yield tmp_path


IN_CYCLE_2 = date(2026, 9, 15)


# ── cycle selection (the bug this module was rewritten for) ─────────────────

def test_date_inside_a_cycle_serves_that_cycle(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)
    assert "Cycle 2" in result
    assert "Cheeseburger" in result


def test_date_in_a_later_month_still_serves_a_cycle_that_covers_it(menu_dir):
    """The regression that took the tool down: October 1-9 2026 is still
    inside the cycle committed as "September", and keying by calendar month
    made the whole tool answer "no menu available" for those eight school
    days."""
    result = get_lunch_menu_text("acme", "6-8", date(2026, 10, 2))
    assert "No lunch menu is available" not in result
    assert "Cheeseburger" in result
    assert "already ENDED" not in result


def test_last_day_of_a_cycle_is_inclusive(menu_dir):
    assert "Cheeseburger" in get_lunch_menu_text("acme", "6-8", date(2026, 10, 9))


def test_first_day_of_a_cycle_is_inclusive(menu_dir):
    assert "Cheeseburger" in get_lunch_menu_text("acme", "6-8", date(2026, 8, 31))


def test_date_picks_the_right_cycle_when_several_are_loaded(two_cycle_dir):
    assert "Cheeseburger" in get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)
    assert "Pulled Pork Sandwich" in get_lunch_menu_text("acme", "6-8", date(2026, 10, 20))


def test_date_in_the_gap_between_cycles_resolves_forward(two_cycle_dir):
    """Oct 10-11 2026 is the weekend between C2 and C3. What's served next
    is C3, so that's the menu to show — flagged as not being today's."""
    result = get_lunch_menu_text("acme", "6-8", date(2026, 10, 10))
    assert "Pulled Pork Sandwich" in result
    assert "no menu is published for today itself" in result
    assert "NEXT period's menu" in result


def test_date_past_every_cycle_serves_the_latest_with_a_staleness_caveat(menu_dir):
    """Nobody has re-run the parser yet. A labelled stale menu beats the
    tool going dark — but the caveat has to be impossible to miss."""
    result = get_lunch_menu_text("acme", "6-8", date(2026, 11, 1))
    assert "Cheeseburger" in result
    assert "already ENDED" in result
    assert "October 9, 2026" in result


def test_date_before_every_cycle_is_treated_as_upcoming(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", date(2026, 8, 1))
    assert "no menu is published for today itself" in result


def test_cycle_missing_its_date_range_is_skipped_not_fatal(tmp_path):
    """A hand-committed file without a usable range must degrade to "no
    menu", never to an exception on an allergy question."""
    _write(tmp_path, {**CYCLE_2, "start_date": None, "end_date": "not-a-date"})
    with patch("app.services.lunch_menu.DATA_DIR", tmp_path):
        assert "No lunch menu is available" in get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)


# ── formatted output ───────────────────────────────────────────────────────

def test_output_states_todays_date_and_the_cycle_range(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)
    assert "Today is September 15, 2026." in result
    assert "August 31, 2026 through October 9, 2026" in result


def test_includes_peanut_tree_nut_free_line_when_true(menu_dir):
    assert "peanut & tree nut free" in get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)


def test_omits_peanut_tree_nut_free_line_when_false(tmp_path):
    _write(tmp_path, {**CYCLE_2, "peanut_tree_nut_free": False})
    with patch("app.services.lunch_menu.DATA_DIR", tmp_path):
        result = get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)
    assert "peanut & tree nut free" not in result


def test_includes_each_days_dishes_and_allergens(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)
    assert "Monday" in result
    assert "Cheeseburger" in result
    assert "wheat, milk" in result
    assert "Tuesday" in result
    assert "Taco Tuesday" in result


def test_dish_with_no_allergens_reads_clearly(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)
    assert "Veggie Bowl (allergens: none listed)" in result


def test_includes_daily_options(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", IN_CYCLE_2)
    assert "Sidekick" in result
    assert "soy, sesame" in result


def test_includes_cycle_notes(two_cycle_dir):
    result = get_lunch_menu_text("acme", "6-8", date(2026, 10, 20))
    assert "No school October 15-16, 2026" in result


def test_missing_grade_band_returns_friendly_message(menu_dir):
    assert "No lunch menu is available" in get_lunch_menu_text("acme", "9-12", IN_CYCLE_2)


def test_missing_district_returns_friendly_message(menu_dir):
    assert "No lunch menu is available" in get_lunch_menu_text("nonexistent", "6-8", IN_CYCLE_2)


# ── get_lunch_menu_urls ────────────────────────────────────────────────────

def test_urls_come_from_the_cycle_being_served(two_cycle_dir):
    """The whole point of storing these per cycle: the cited PDFs always
    describe the dishes actually being quoted."""
    assert get_lunch_menu_urls("acme", "6-8", IN_CYCLE_2) == (
        "https://example.test/c2_menu.pdf", "https://example.test/c2_nutrition.pdf")
    assert get_lunch_menu_urls("acme", "6-8", date(2026, 10, 20)) == (
        "https://example.test/c3_menu.pdf", "https://example.test/c3_nutrition.pdf")


def test_urls_are_none_when_no_cycle_is_available(menu_dir):
    assert get_lunch_menu_urls("nonexistent", "6-8", IN_CYCLE_2) == (None, None)


def test_urls_are_none_when_the_cycle_omits_them(tmp_path):
    _write(tmp_path, {k: v for k, v in CYCLE_2.items() if not k.endswith("_url")})
    with patch("app.services.lunch_menu.DATA_DIR", tmp_path):
        assert get_lunch_menu_urls("acme", "6-8", IN_CYCLE_2) == (None, None)

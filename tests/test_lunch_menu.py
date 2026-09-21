"""Unit tests for the lunch menu service (app/services/lunch_menu.py)."""
import json
from unittest.mock import patch

import pytest

from app.services.lunch_menu import get_lunch_menu_text


@pytest.fixture()
def menu_dir(tmp_path):
    grade_band_dir = tmp_path / "acme" / "6-8"
    grade_band_dir.mkdir(parents=True)
    (grade_band_dir / "2026_09.json").write_text(json.dumps({
        "period_label": "September 2026",
        "peanut_tree_nut_free": True,
        "days": {
            "Monday": [
                {"name": "Cheeseburger", "allergens": ["wheat", "milk"]},
                {"name": "Veggie Bowl", "allergens": []},
            ],
            "Tuesday": [{"name": "Taco Tuesday", "allergens": ["wheat", "milk", "soy"]}],
        },
        "daily_options": [{"name": "Sidekick", "allergens": ["soy", "sesame"]}],
    }))
    with patch("app.services.lunch_menu.DATA_DIR", tmp_path):
        yield


def test_get_lunch_menu_text_includes_period_label(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", "2026_09")
    assert "September 2026" in result


def test_get_lunch_menu_text_includes_peanut_tree_nut_free_line_when_true(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", "2026_09")
    assert "peanut & tree nut free" in result


def test_get_lunch_menu_text_omits_peanut_tree_nut_free_line_when_false(tmp_path):
    grade_band_dir = tmp_path / "acme" / "6-8"
    grade_band_dir.mkdir(parents=True)
    (grade_band_dir / "2026_09.json").write_text(json.dumps({
        "period_label": "September 2026",
        "peanut_tree_nut_free": False,
        "days": {},
        "daily_options": [],
    }))
    with patch("app.services.lunch_menu.DATA_DIR", tmp_path):
        result = get_lunch_menu_text("acme", "6-8", "2026_09")
    assert "peanut & tree nut free" not in result


def test_get_lunch_menu_text_includes_each_days_dishes_and_allergens(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", "2026_09")
    assert "Monday" in result
    assert "Cheeseburger" in result
    assert "wheat, milk" in result
    assert "Tuesday" in result
    assert "Taco Tuesday" in result


def test_get_lunch_menu_text_dish_with_no_allergens_reads_clearly(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", "2026_09")
    assert "Veggie Bowl (allergens: none listed)" in result


def test_get_lunch_menu_text_includes_daily_options(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", "2026_09")
    assert "Sidekick" in result
    assert "soy, sesame" in result


def test_get_lunch_menu_text_missing_month_returns_friendly_message(menu_dir):
    result = get_lunch_menu_text("acme", "6-8", "2099_01")
    assert "No lunch menu is available" in result


def test_get_lunch_menu_text_missing_grade_band_returns_friendly_message(menu_dir):
    result = get_lunch_menu_text("acme", "9-12", "2026_09")
    assert "No lunch menu is available" in result


def test_get_lunch_menu_text_missing_district_returns_friendly_message(menu_dir):
    result = get_lunch_menu_text("nonexistent", "6-8", "2026_09")
    assert "No lunch menu is available" in result

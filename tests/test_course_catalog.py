"""Unit tests for the course catalog service (app/services/course_catalog.py)."""
import json
from unittest.mock import patch

import pytest

from app.services.course_catalog import get_course_catalog_section, get_department_names


@pytest.fixture()
def catalog_dir(tmp_path):
    district_dir = tmp_path / "acme"
    district_dir.mkdir()
    (district_dir / "2026_27.json").write_text(json.dumps({
        "school_year": "2026-27",
        "overview": "Graduation requires 230 credits.",
        "departments": {
            "Engineering": "PLTW Introduction to Engineering Design...",
            "Mathematics": "Algebra I, Geometry, Algebra II...",
        },
    }))
    with patch("app.services.course_catalog.DATA_DIR", tmp_path):
        yield


def test_get_department_names_returns_catalog_order(catalog_dir):
    assert get_department_names("acme", "2026_27") == ["Engineering", "Mathematics"]


def test_get_department_names_missing_district_returns_empty(catalog_dir):
    assert get_department_names("nonexistent", "2026_27") == []


def test_get_course_catalog_section_no_department_returns_overview(catalog_dir):
    result = get_course_catalog_section("acme", department=None, year_key="2026_27")
    assert "230 credits" in result


def test_get_course_catalog_section_with_department_returns_that_section(catalog_dir):
    result = get_course_catalog_section("acme", department="Engineering", year_key="2026_27")
    assert "PLTW" in result
    assert "230 credits" not in result


def test_get_course_catalog_section_is_case_insensitive(catalog_dir):
    result = get_course_catalog_section("acme", department="engineering", year_key="2026_27")
    assert "PLTW" in result


def test_get_course_catalog_section_unknown_department_lists_available(catalog_dir):
    """A department name the model got wrong (typo, hallucinated) must fail
    with actionable guidance, not silently return the wrong section or an
    opaque error the agent can't recover from."""
    result = get_course_catalog_section("acme", department="Chemistry", year_key="2026_27")
    assert "not a recognized department" in result
    assert "Engineering" in result
    assert "Mathematics" in result


def test_get_course_catalog_section_missing_catalog_file(catalog_dir):
    result = get_course_catalog_section("nonexistent", department=None, year_key="2026_27")
    assert "No course catalog" in result

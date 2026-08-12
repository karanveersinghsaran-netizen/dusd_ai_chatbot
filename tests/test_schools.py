"""Unit tests for the school registry (app/schools.py)."""
from pathlib import Path

from app.schools import get_school, load_schools


def test_load_schools_includes_known_schools():
    schools = load_schools()
    assert {"wells", "dhs"} <= set(schools.keys())


def test_get_school_returns_none_for_unknown_id():
    assert get_school("nonexistent-school") is None


def test_get_school_returns_matching_config():
    wells = get_school("wells")
    assert wells.id == "wells"
    assert wells.name == "Wells Middle School"
    assert wells.website == "https://wms.dublinusd.org/"


def test_wells_has_campus_map_file():
    wells = get_school("wells")
    assert isinstance(wells.campus_map_file, Path)
    assert wells.campus_map_file.exists()


def test_dhs_has_no_campus_map_file():
    """DHS has no authored floor plan, so get_campus_directions shouldn't be
    registered for it (see app/agent.py's conditional tool)."""
    dhs = get_school("dhs")
    assert dhs.campus_map_file is None


def test_schools_have_distinct_allowed_origins():
    schools = load_schools()
    origins = [s.allowed_origin for s in schools.values()]
    assert len(origins) == len(set(origins))


def test_pages_is_dict_of_url_lists():
    wells = get_school("wells")
    assert isinstance(wells.pages, dict)
    assert "home" in wells.pages
    assert all(isinstance(urls, list) for urls in wells.pages.values())

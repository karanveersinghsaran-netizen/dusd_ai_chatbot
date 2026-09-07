"""Unit tests for the school registry (app/schools.py)."""
import json
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


def test_dhs_has_campus_map_file():
    dhs = get_school("dhs")
    assert isinstance(dhs.campus_map_file, Path)
    assert dhs.campus_map_file.exists()


def test_pages_is_dict_of_url_lists():
    wells = get_school("wells")
    assert isinstance(wells.pages, dict)
    assert "home" in wells.pages
    assert all(isinstance(urls, list) for urls in wells.pages.values())


# ── Per-school theming (#52) ────────────────────────────────────────────────

def test_wells_has_theme_colors():
    wells = get_school("wells")
    assert wells.theme_color == "#00695c"
    assert wells.primary_bubble_color == "#00695c"
    assert wells.background_tint == "#eef7f6"


def test_dhs_has_theme_colors():
    dhs = get_school("dhs")
    assert dhs.theme_color == "#0a2472"
    assert dhs.primary_bubble_color == "#0a2472"
    assert dhs.background_tint == "#eef1f8"


def test_logo_url_defaults_to_none_when_no_real_asset_exists():
    """Neither school has a real logo file yet (#52 open question) — the
    chatbox falls back to an initials placeholder rather than a broken img."""
    assert get_school("wells").logo_url is None
    assert get_school("dhs").logo_url is None


def test_theme_fields_default_to_none_when_absent_from_json(tmp_path, monkeypatch):
    """A school.json written before #52 (no theme_color/etc. keys) must still
    load — onboarding theming is opt-in per school, not a breaking schema
    change."""
    import app.schools as schools_module

    school_dir = tmp_path / "legacy"
    school_dir.mkdir()
    (school_dir / "school.json").write_text(
        json.dumps(
            {
                "id": "legacy",
                "name": "Legacy School",
                "district": "Dublin Unified School District",
                "district_id": "dusd",
                "website": "https://legacy.dublinusd.org/",
                "rss_url": "https://legacy.dublinusd.org/rss",
            }
        )
    )
    monkeypatch.setattr(schools_module, "SCHOOLS_DIR", tmp_path)
    schools_module.load_schools.cache_clear()
    try:
        legacy = schools_module.get_school("legacy")
        assert legacy.theme_color is None
        assert legacy.primary_bubble_color is None
        assert legacy.background_tint is None
        assert legacy.logo_url is None
    finally:
        schools_module.load_schools.cache_clear()

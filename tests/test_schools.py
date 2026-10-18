"""Unit tests for the school registry (app/schools.py)."""
import json
from pathlib import Path

import pytest

from app.schools import get_school, load_schools


def test_load_schools_includes_known_schools():
    schools = load_schools()
    assert {"wells", "dhs", "fallon", "emerald"} <= set(schools.keys())


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


# ── Translated useful links (#62) ───────────────────────────────────────────

def test_wells_has_translated_useful_links():
    wells = get_school("wells")
    assert wells.useful_links_es is not None
    assert wells.useful_links_zh is not None
    assert "Portal para padres" in wells.useful_links_es
    assert "家长门户网站" in wells.useful_links_zh


def test_dhs_has_translated_useful_links():
    dhs = get_school("dhs")
    assert dhs.useful_links_es is not None
    assert dhs.useful_links_zh is not None
    assert "Centro Universitario" in dhs.useful_links_es
    assert "大学与职业中心" in dhs.useful_links_zh


def test_useful_links_translations_default_to_none_when_absent_from_json(tmp_path, monkeypatch):
    """A school.json written before #62 (no useful_links_es/_zh keys) must
    still load — translations are opt-in per school, not a breaking schema
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
        assert legacy.useful_links_es is None
        assert legacy.useful_links_zh is None
    finally:
        schools_module.load_schools.cache_clear()


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


# ── Fallon and Emerald (#169) ──────────────────────────────────────────────

@pytest.mark.parametrize("school_id", ["wells", "dhs", "fallon", "emerald"])
def test_every_school_has_the_fields_the_agent_relies_on(school_id):
    """Runs over EVERY school rather than naming two, so onboarding a school
    with a missing field fails here instead of at request time — load_schools
    is lazy, so a bad config surfaces as a 500 on a live question."""
    school = get_school(school_id)

    assert school.name and school.district_id and school.website
    assert school.rss_url.startswith("https://")
    assert school.phone and school.address and school.office_hours
    assert school.bell_schedule.strip()
    assert school.useful_links.strip()
    assert isinstance(school.pages, dict) and "home" in school.pages
    assert all(isinstance(urls, list) and urls for urls in school.pages.values())


@pytest.mark.parametrize("school_id", ["wells", "dhs", "fallon", "emerald"])
def test_every_school_page_group_is_a_name_the_tool_accepts(school_id):
    """get_school_information's page_group enum is a closed set — a typo in a
    school.json key would make that group permanently unreachable, silently."""
    allowed = {
        "home", "principal", "staff", "academics", "counseling", "attendance",
        "clubs", "athletics", "family", "enrollment", "technology",
    }

    assert set(get_school(school_id).pages) <= allowed


@pytest.mark.parametrize("school_id", ["wells", "dhs", "fallon", "emerald"])
def test_every_school_has_translated_useful_links(school_id):
    school = get_school(school_id)

    assert school.useful_links_es and school.useful_links_zh
    # Same number of entries in each language — a dropped line means a
    # Spanish or Mandarin user silently loses a link.
    assert (len(school.useful_links.strip().splitlines())
            == len(school.useful_links_es.strip().splitlines())
            == len(school.useful_links_zh.strip().splitlines()))


def test_fallon_is_a_middle_school_with_the_6_8_lunch_menu():
    """Fallon shares Wells' grade band, so it reuses the already-parsed
    6-8 menu data — no new parsing, and the allergen sets are the ones
    already hand-verified against the district PDFs."""
    fallon = get_school("fallon")

    assert fallon.lunch_menu_grade_band == "6-8"
    assert fallon.has_course_catalog is False
    assert fallon.district_id == "dusd"


def test_emerald_is_a_high_school_with_the_9_12_menu_and_the_catalog():
    """The district's Grades 9-12 catalog states that all courses are offered
    at both Dublin High and Emerald unless a course names a site, so the
    catalog tool applies to Emerald too."""
    emerald = get_school("emerald")

    assert emerald.lunch_menu_grade_band == "9-12"
    assert emerald.has_course_catalog is True
    assert emerald.course_catalog_url == get_school("dhs").course_catalog_url


@pytest.mark.parametrize("school_id", ["fallon", "emerald"])
def test_new_schools_have_theme_colors(school_id):
    school = get_school(school_id)

    assert school.theme_color.startswith("#")
    assert school.primary_bubble_color.startswith("#")
    assert school.background_tint.startswith("#")


@pytest.mark.parametrize("school_id", ["fallon", "emerald"])
def test_new_schools_claim_no_campus_map(school_id):
    """Neither has a digitised campus map yet, so get_campus_directions must
    stay unregistered rather than answering from nothing."""
    assert get_school(school_id).campus_map_file is None


def test_theme_colors_are_distinct_across_schools():
    """The colour is how a user can tell which school's chatbox they have
    open, so two schools sharing one defeats the purpose."""
    colors = [get_school(s).theme_color for s in ("wells", "dhs", "fallon", "emerald")]

    assert len(set(colors)) == len(colors), colors


# ── school level drives the chatbox pickers (#175) ────────────────────────

@pytest.mark.parametrize("school_id", ["wells", "dhs", "fallon", "emerald"])
def test_every_school_declares_a_level(school_id):
    """level groups schools into the chatbox's Middle/High dropdowns. A
    school without one lands in a catch-all "School" group, which is a
    visible wart rather than a crash — so assert it over every school."""
    assert get_school(school_id).level in {"middle", "high"}


def test_levels_match_the_grade_bands_they_serve():
    """level is declared separately from lunch_menu_grade_band on purpose
    (a school with no menu has no band), but where both exist they must not
    contradict each other."""
    expected = {"6-8": "middle", "9-12": "high"}
    for school_id in ("wells", "dhs", "fallon", "emerald"):
        school = get_school(school_id)
        if school.lunch_menu_grade_band:
            assert school.level == expected[school.lunch_menu_grade_band], school_id


def test_each_level_has_a_default_school_the_picker_can_select():
    """The chatbox defaults Middle to wells and High to dhs; both have to
    exist and sit in the level they're the default for."""
    assert get_school("wells").level == "middle"
    assert get_school("dhs").level == "high"


def test_level_defaults_to_none_when_absent_from_json(tmp_path, monkeypatch):
    """An older school.json without the field must still load."""
    school_dir = tmp_path / "noleveltest"
    school_dir.mkdir()
    (school_dir / "school.json").write_text(json.dumps({
        "id": "noleveltest", "name": "No Level School", "district": "D",
        "district_id": "d", "website": "https://x.test/", "rss_url": "https://x.test/rss",
    }), encoding="utf-8")
    monkeypatch.setattr("app.schools.SCHOOLS_DIR", tmp_path)
    load_schools.cache_clear()
    try:
        assert load_schools()["noleveltest"].level is None
    finally:
        load_schools.cache_clear()

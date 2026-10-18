"""School registry: loads per-school configuration from data/schools/<id>/school.json.

Onboarding a new school is adding a directory here — no code change required
unless the school needs behavior beyond what SchoolConfig expresses (e.g. a
tool no other school uses).
"""
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

SCHOOLS_DIR = Path(__file__).resolve().parents[1] / "data" / "schools"


@dataclass(frozen=True)
class SchoolConfig:
    id: str
    name: str
    district: str
    district_id: str
    # Which picker group this school belongs to in the chatbox — "middle" or
    # "high" today. Explicit rather than inferred from lunch_menu_grade_band:
    # that field exists to select menu DATA and is None for a school with no
    # menu, which would silently drop it out of the picker.
    level: Optional[str]
    website: str
    rss_url: str
    phone: str
    address: str
    fax: str
    office_hours: str
    bell_schedule: str
    useful_links: str
    pages: Dict[str, List[str]] = field(default_factory=dict)
    campus_map_file: Optional[Path] = None
    donation_url: Optional[str] = None
    clubs_sheet_url: Optional[str] = None
    # Where the bell schedule itself is published — cited as the SOURCE
    # for bell-schedule questions instead of the generic school website,
    # since that's the page/document a parent can actually cross-check
    # times against. Falls back to school.website if unset.
    bell_schedule_url: Optional[str] = None
    # Gates the get_course_catalog tool (app/agent.py) — the district's
    # Grades 9-12 course catalog (data/course_catalogs/<district_id>/) only
    # applies to comprehensive high schools, not middle schools, so this
    # must be opted into per school rather than inferred from district_id
    # (both a middle school and its high school share the same district_id).
    has_course_catalog: bool = False
    # Where the course catalog itself is published — cited as the SOURCE for
    # course-catalog questions instead of the generic school website, same
    # reasoning as bell_schedule_url. Falls back to school.website if unset.
    course_catalog_url: Optional[str] = None
    # Gates the get_lunch_menu tool (app/agent.py) — which grade band's menu
    # (data/lunch_menus/<district_id>/<grade_band>/) applies to this school.
    # None means no lunch menu tool for this school. Unlike
    # has_course_catalog, this single field both gates the tool AND selects
    # the data (same "presence gates it" shape as campus_map_file/
    # clubs_sheet_url) since the grade-band value itself is what's needed.
    lunch_menu_grade_band: Optional[str] = None
    # FALLBACK source link for lunch-menu questions. The real source is the
    # menu_url recorded inside the cycle JSON being served, which the agent
    # prefers — it's the document that cycle's data was actually parsed
    # from, so it can't cite the wrong month's PDF for the dishes being
    # quoted. These two fields exist for a school whose cycle files predate
    # that convention (or lack the URLs), and fall back in turn to
    # school.website.
    lunch_menu_url: Optional[str] = None
    # The nutrition PDF (per-ingredient allergen detail) that
    # lunch_menu_url's calendar PDF doesn't itself show — offered as a
    # secondary, more detailed source when a user wants to verify allergen
    # info themselves. Same fallback role as lunch_menu_url.
    lunch_menu_nutrition_url: Optional[str] = None
    # Per-school branding (#52). All optional so a school.json that predates
    # theming still loads — callers fall back to the neutral blue theme when
    # these are absent. logo_url is None for both current schools (no real
    # logo assets exist yet); the chatbox renders an initials placeholder.
    theme_color: Optional[str] = None
    primary_bubble_color: Optional[str] = None
    background_tint: Optional[str] = None
    logo_url: Optional[str] = None
    # Per-user daily message cap override (#71) — cost/abuse guard on /chat.
    # None means "use the district-wide default" (config.DEFAULT_DAILY_MESSAGE_CAP);
    # set here only for a school that needs a different number.
    daily_message_cap: Optional[int] = None
    # Translated useful-links labels (#62), for the ES/ZH chatbox toggle.
    # Optional — a school.json without these still loads fine and the agent
    # just shares the English list regardless of response language.
    useful_links_es: Optional[str] = None
    useful_links_zh: Optional[str] = None


def _load_school(school_dir: Path) -> SchoolConfig:
    raw = json.loads((school_dir / "school.json").read_text(encoding="utf-8"))

    campus_map_file = None
    if raw.get("campus_map_file"):
        campus_map_file = school_dir / raw["campus_map_file"]

    return SchoolConfig(
        id=raw["id"],
        name=raw["name"],
        district=raw["district"],
        district_id=raw["district_id"],
        level=raw.get("level"),
        website=raw["website"],
        rss_url=raw["rss_url"],
        phone=raw.get("phone", ""),
        address=raw.get("address", ""),
        fax=raw.get("fax", ""),
        office_hours=raw.get("office_hours", ""),
        bell_schedule=raw.get("bell_schedule", ""),
        useful_links=raw.get("useful_links", ""),
        pages=raw.get("pages", {}),
        campus_map_file=campus_map_file,
        donation_url=raw.get("donation_url"),
        clubs_sheet_url=raw.get("clubs_sheet_url"),
        bell_schedule_url=raw.get("bell_schedule_url"),
        has_course_catalog=raw.get("has_course_catalog", False),
        course_catalog_url=raw.get("course_catalog_url"),
        lunch_menu_grade_band=raw.get("lunch_menu_grade_band"),
        lunch_menu_url=raw.get("lunch_menu_url"),
        lunch_menu_nutrition_url=raw.get("lunch_menu_nutrition_url"),
        theme_color=raw.get("theme_color"),
        primary_bubble_color=raw.get("primary_bubble_color"),
        background_tint=raw.get("background_tint"),
        logo_url=raw.get("logo_url"),
        daily_message_cap=raw.get("daily_message_cap"),
        useful_links_es=raw.get("useful_links_es"),
        useful_links_zh=raw.get("useful_links_zh"),
    )


@lru_cache
def load_schools() -> Dict[str, SchoolConfig]:
    """Load every school under data/schools/. Cached — call clear() in tests
    that need to reload after writing fixture files."""
    schools = {}
    if not SCHOOLS_DIR.is_dir():
        return schools
    for school_dir in sorted(SCHOOLS_DIR.iterdir()):
        if not school_dir.is_dir():
            continue
        school = _load_school(school_dir)
        schools[school.id] = school
    return schools


def get_school(school_id: str) -> Optional[SchoolConfig]:
    return load_schools().get(school_id)

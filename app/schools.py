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
        theme_color=raw.get("theme_color"),
        primary_bubble_color=raw.get("primary_bubble_color"),
        background_tint=raw.get("background_tint"),
        logo_url=raw.get("logo_url"),
        daily_message_cap=raw.get("daily_message_cap"),
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

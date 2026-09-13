"""Course catalog service — DUSD's grades 9-12 course catalog, chunked by
department (see scripts/parse_course_catalog.py) so a tool call returns one
relevant section instead of the ~1MB source document. Shared per district,
same file layout and year-key convention as app/services/calendar.py:
data/course_catalogs/<district_id>/<YYYY_YY>.json.
"""
import json
from pathlib import Path
from typing import List, Optional

from app.timezone_utils import pacific_today

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "course_catalogs"


def _current_school_year_key() -> str:
    """Same convention as app.services.calendar._current_school_year_key —
    DUSD's school year starts in August."""
    today = pacific_today()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}_{str(start_year + 1)[2:]}"


def _load_catalog(district_id: str, year_key: Optional[str] = None) -> Optional[dict]:
    key = year_key or _current_school_year_key()
    path = DATA_DIR / district_id / f"{key}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_department_names(district_id: str, year_key: Optional[str] = None) -> List[str]:
    """Every department name available for this district/year, in catalog
    order — used to build the get_course_catalog tool's department enum."""
    catalog = _load_catalog(district_id, year_key)
    if not catalog:
        return []
    return list(catalog.get("departments", {}).keys())


def get_course_catalog_section(
    district_id: str, department: Optional[str] = None, year_key: Optional[str] = None
) -> str:
    """Returns the front-matter overview (graduation requirements, UC/CSU
    tables, grading and schedule-change policies) when department is
    None/empty, else that department's full course listing. Department
    match is case-insensitive."""
    catalog = _load_catalog(district_id, year_key)
    if not catalog:
        return "No course catalog is available for this school."

    if not department:
        return catalog.get("overview", "")

    departments = catalog.get("departments", {})
    normalized = department.strip().lower()
    for name, text in departments.items():
        if name.lower() == normalized:
            return text

    available = ", ".join(departments.keys())
    return f"'{department}' is not a recognized department. Available departments: {available}."

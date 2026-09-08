"""
Calendar service, shared across all schools.

Combines two data sources:
  1. RSS feed  — live school events (assemblies, sports, performances, etc.),
     per school (each school passes its own rss_url).
  2. JSON data — instructional calendar (no-school days, breaks, min days),
     shared per district. Files live in data/calendars/<district_id>/<YYYY_YY>.json
     and are loaded automatically based on the current school year.
"""
import json
import requests
import urllib3
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Dict, Optional
from urllib.parse import urlparse, parse_qs

from app.timezone_utils import pacific_today

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "calendars"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# District calendar (JSON-backed)
# ---------------------------------------------------------------------------

def _fmt_date(d: date) -> str:
    """Canonical tool-output date format: ISO date + day-of-week, e.g.
    '2026-11-04 (Wednesday)'. Tool responses stay unambiguous and machine-
    parseable; the agent is responsible for phrasing dates for the user
    (see the system prompt's DATE HANDLING rules in app/agent.py)."""
    return f"{d.isoformat()} ({d.strftime('%A')})"


def _school_year_key_for(d: date) -> str:
    """Return the JSON filename stem for the school year containing date `d`
    (e.g. '2025_26'). DUSD's school year starts in August."""
    start_year = d.year if d.month >= 8 else d.year - 1
    return f"{start_year}_{str(start_year + 1)[2:]}"


def _current_school_year_key() -> str:
    """Return the JSON filename stem for the current school year (e.g. '2025_26')."""
    return _school_year_key_for(pacific_today())


def _load_district_calendar(district_id: str, year_key: str = None) -> dict:
    """Load the JSON calendar for the given district and school year key (e.g.
    '2025_26'), or current year if omitted."""
    key = year_key or _current_school_year_key()
    path = DATA_DIR / district_id / f"{key}.json"
    if not path.exists():
        return {}
    with open(path, "r") as f:
        raw = json.load(f)

    # Convert date strings to date objects
    def to_date(s):
        return date.fromisoformat(s)

    return {
        "first_day":      to_date(raw.get("first_day", "1900-01-01")),
        "last_day":       to_date(raw.get("last_day",  "1900-01-01")),
        "no_school_days": {to_date(k): v for k, v in raw.get("no_school_days", {}).items()},
        "breaks":         [{"name": b["name"], "start": to_date(b["start"]), "end": to_date(b["end"])}
                           for b in raw.get("breaks", [])],
        "minimum_days":   {to_date(k): v for k, v in raw.get("minimum_days", {}).items()},
        "academic_dates": {to_date(k): v for k, v in raw.get("academic_dates", {}).items()},
    }


def _next_school_day(after: date, cal: dict) -> date:
    d = after + timedelta(days=1)
    while True:
        if d.weekday() < 5 and d not in cal.get("no_school_days", {}):
            in_break = any(b["start"] <= d <= b["end"] for b in cal.get("breaks", []))
            if not in_break:
                return d
        d += timedelta(days=1)


def get_school_day_status(today: date, district_id: str) -> str:
    """School status for a given date. Dates are rendered as ISO + day-of-week
    (canonical tool output) — the agent phrases them for the user."""
    if today is None:
        today = pacific_today()

    cal = _load_district_calendar(district_id)
    if not cal:
        return ""

    date_str = _fmt_date(today)

    if today.weekday() >= 5:
        return f"{date_str} is a weekend — no school."

    for brk in cal.get("breaks", []):
        if brk["start"] <= today <= brk["end"]:
            resumes = _next_school_day(brk["end"], cal)
            return (
                f"{date_str} is during {brk['name']} "
                f"({_fmt_date(brk['start'])} – {_fmt_date(brk['end'])}). "
                f"School resumes on {_fmt_date(resumes)}."
            )

    if today in cal.get("no_school_days", {}):
        return f"{date_str} is {cal['no_school_days'][today]} — no school."

    if today in cal.get("minimum_days", {}):
        return f"{date_str} is a school day ({cal['minimum_days'][today]})."

    if today in cal.get("academic_dates", {}):
        return f"{date_str} is a school day ({cal['academic_dates'][today]})."

    if today < cal.get("first_day", today):
        return f"School has not started yet. First day is {_fmt_date(cal['first_day'])}."

    if today > cal.get("last_day", today):
        next_cal = _load_district_calendar(district_id, _next_year_key(_current_school_year_key()))
        if next_cal and next_cal.get("first_day"):
            return (f"The school year has ended (last day was {_fmt_date(cal['last_day'])}). "
                    f"Next school year starts on {_fmt_date(next_cal['first_day'])}.")
        return f"The school year has ended (last day was {_fmt_date(cal['last_day'])})."

    return f"{date_str} is a regular school day."


def _next_year_key(key: str) -> str:
    """Return the key for the following school year (e.g. '2025_26' -> '2026_27')."""
    start_year = int(key.split("_")[0]) + 1
    return f"{start_year}_{str(start_year + 1)[2:]}"


def get_upcoming_no_school_days(today: date, district_id: str, limit: int = 20) -> str:
    """Return the next few no-school days and breaks, spanning into next year if needed."""
    if today is None:
        today = pacific_today()

    current_key = _current_school_year_key()
    next_key = _next_year_key(current_key)
    calendars = [_load_district_calendar(district_id, current_key), _load_district_calendar(district_id, next_key)]

    upcoming = []
    for cal in calendars:
        if not cal:
            continue
        for brk in cal.get("breaks", []):
            if brk["end"] >= today:
                upcoming.append((brk["start"], f"{brk['name']} ({_fmt_date(brk['start'])} – {_fmt_date(brk['end'])})"))
        for d, reason in cal.get("no_school_days", {}).items():
            if d >= today:
                upcoming.append((d, f"{_fmt_date(d)}: {reason}"))
        for d, reason in cal.get("academic_dates", {}).items():
            if d >= today:
                upcoming.append((d, f"{_fmt_date(d)}: {reason} (regular school day, not a day off)"))

    upcoming.sort(key=lambda x: x[0])
    seen, result = set(), []
    for d, label in upcoming:
        if d not in seen:
            result.append(label)
            seen.add(d)
        if len(result) >= limit:
            break

    if not result:
        return "No upcoming no-school days found."
    return "Upcoming no-school days:\n" + "\n".join(f"- {r}" for r in result)


def count_school_days_until(today: date, target: date, district_id: str) -> int:
    """Count school days strictly between `today` (exclusive) and `target`
    (exclusive) — a weekday that is not a no-school day and does not fall
    within a break. Loads every school-year calendar the range spans (e.g.
    a query crossing from spring into the next school year), so answers to
    "how many school days until <date>" stay correct even near a year
    boundary. Returns 0 if `target` is not after `today`."""
    if target <= today:
        return 0

    keys = [_school_year_key_for(today)]
    target_key = _school_year_key_for(target)
    while keys[-1] != target_key:
        keys.append(_next_year_key(keys[-1]))

    no_school_days: set = set()
    breaks: List[Dict] = []
    for key in keys:
        cal = _load_district_calendar(district_id, key)
        if not cal:
            continue
        no_school_days.update(cal.get("no_school_days", {}).keys())
        breaks.extend(cal.get("breaks", []))

    count = 0
    d = today + timedelta(days=1)
    while d < target:
        if (
            d.weekday() < 5
            and d not in no_school_days
            and not any(b["start"] <= d <= b["end"] for b in breaks)
        ):
            count += 1
        d += timedelta(days=1)
    return count


# ---------------------------------------------------------------------------
# RSS calendar (live school events)
# ---------------------------------------------------------------------------

def _parse_end_date(link: str, start: date) -> date:
    try:
        qs = parse_qs(urlparse(link).query)
        if "mDateTo" in qs:
            return date.fromisoformat(qs["mDateTo"][0])
    except Exception:
        pass
    return start


def _fetch_rss_events(rss_url: str) -> List[Dict]:
    response = requests.get(rss_url, timeout=10, verify=False, headers=HEADERS)
    response.raise_for_status()
    root = ET.fromstring(response.content)
    channel = root.find("channel")
    events = []
    for item in channel.findall("item"):
        title = item.findtext("title", "").strip()
        pub_date_str = item.findtext("pubDate", "").strip()
        description = item.findtext("description", "").strip()
        link = item.findtext("link", "").strip()
        if not pub_date_str:
            continue
        try:
            start_dt = parsedate_to_datetime(pub_date_str)
        except Exception:
            continue
        start = start_dt.date()
        end = _parse_end_date(link, start)
        desc_lines = [l.strip() for l in description.splitlines() if l.strip()]
        events.append({
            "title": title,
            "start": start,
            "end":   end,
            "description": " | ".join(desc_lines) if desc_lines else "",
        })
    return events


def get_today_status(rss_url: str, today: Optional[date] = None) -> str:
    """Return ongoing RSS events today (injected into system prompt)."""
    try:
        if today is None:
            today = pacific_today()
        ongoing = [e for e in _fetch_rss_events(rss_url) if e["start"] <= today <= e["end"]]
        if not ongoing:
            return ""
        titles = ", ".join(e["title"] for e in ongoing)
        return f"NOTE: Today ({_fmt_date(today)}) the following events are ongoing: {titles}."
    except Exception:
        return ""


def get_upcoming_events(rss_url: str, today: Optional[date] = None) -> str:
    """Return upcoming and ongoing RSS events sorted by start date."""
    try:
        if today is None:
            today = pacific_today()
        events = [e for e in _fetch_rss_events(rss_url) if e["end"] >= today]
        if not events:
            return "No upcoming events found on the school calendar."

        events.sort(key=lambda e: e["start"])
        lines = ["Upcoming Events:\n"]
        for e in events:
            if e["start"] == e["end"]:
                date_str = _fmt_date(e["start"])
            else:
                date_str = f"{_fmt_date(e['start'])} - {_fmt_date(e['end'])}"
            tag = " [ONGOING TODAY]" if e["start"] <= today <= e["end"] else ""
            line = f"- {date_str}: {e['title']}{tag}"
            if e["description"]:
                line += f" ({e['description']})"
            lines.append(line)
        return "\n".join(lines)
    except Exception as ex:
        return f"Error fetching calendar: {str(ex)}"

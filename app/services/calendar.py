"""
Calendar service for Wells Middle School.

Combines two data sources:
  1. RSS feed  — live school events (assemblies, sports, performances, etc.)
  2. JSON data — DUSD instructional calendar (no-school days, breaks, min days)
     Files live in data/calendars/<YYYY_YY>.json and are loaded automatically
     based on the current school year.
"""
import json
import requests
import urllib3
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import List, Dict
from urllib.parse import urlparse, parse_qs

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RSS_URL = "https://wms.dublinusd.org/apps/events/events_rss.jsp?id=0"
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

def _current_school_year_key() -> str:
    """Return the JSON filename stem for the current school year (e.g. '2025_26')."""
    today = date.today()
    start_year = today.year if today.month >= 8 else today.year - 1
    return f"{start_year}_{str(start_year + 1)[2:]}"


def _load_district_calendar(year_key: str = None) -> dict:
    """Load the JSON calendar for the given school year key (e.g. '2025_26'), or current year if omitted."""
    key = year_key or _current_school_year_key()
    path = DATA_DIR / f"{key}.json"
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


def get_school_day_status(today: date = None) -> str:
    """Plain-English school status for a given date."""
    if today is None:
        today = date.today()

    cal = _load_district_calendar()
    if not cal:
        return ""

    date_str = today.strftime("%A, %B %d, %Y")

    if today.weekday() >= 5:
        return f"{date_str} is a weekend — no school."

    for brk in cal.get("breaks", []):
        if brk["start"] <= today <= brk["end"]:
            resumes = _next_school_day(brk["end"], cal)
            return (
                f"{date_str} is during {brk['name']} "
                f"({brk['start'].strftime('%B %d')} – {brk['end'].strftime('%B %d, %Y')}). "
                f"School resumes on {resumes.strftime('%A, %B %d, %Y')}."
            )

    if today in cal.get("no_school_days", {}):
        return f"{date_str} is {cal['no_school_days'][today]} — no school."

    if today in cal.get("minimum_days", {}):
        return f"{date_str} is a school day ({cal['minimum_days'][today]})."

    if today in cal.get("academic_dates", {}):
        return f"{date_str} is a school day ({cal['academic_dates'][today]})."

    if today < cal.get("first_day", today):
        return f"School has not started yet. First day is {cal['first_day'].strftime('%B %d, %Y')}."

    if today > cal.get("last_day", today):
        next_cal = _load_district_calendar(_next_year_key(_current_school_year_key()))
        if next_cal and next_cal.get("first_day"):
            return (f"The school year has ended (last day was {cal['last_day'].strftime('%B %d, %Y')}). "
                    f"Next school year starts on {next_cal['first_day'].strftime('%B %d, %Y')}.")
        return f"The school year has ended (last day was {cal['last_day'].strftime('%B %d, %Y')})."

    return f"{date_str} is a regular school day."


def _next_year_key(key: str) -> str:
    """Return the key for the following school year (e.g. '2025_26' -> '2026_27')."""
    start_year = int(key.split("_")[0]) + 1
    return f"{start_year}_{str(start_year + 1)[2:]}"


def get_upcoming_no_school_days(today: date = None, limit: int = 20) -> str:
    """Return the next few no-school days and breaks, spanning into next year if needed."""
    if today is None:
        today = date.today()

    current_key = _current_school_year_key()
    next_key = _next_year_key(current_key)
    calendars = [_load_district_calendar(current_key), _load_district_calendar(next_key)]

    upcoming = []
    for cal in calendars:
        if not cal:
            continue
        for brk in cal.get("breaks", []):
            if brk["end"] >= today:
                upcoming.append((brk["start"], f"{brk['name']} ({brk['start'].strftime('%B %d')} – {brk['end'].strftime('%B %d, %Y')})"))
        for d, reason in cal.get("no_school_days", {}).items():
            if d >= today:
                upcoming.append((d, f"{d.strftime('%B %d, %Y')}: {reason}"))
        for d, reason in cal.get("academic_dates", {}).items():
            if d >= today:
                upcoming.append((d, f"{d.strftime('%B %d, %Y')}: {reason}"))

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


def _fetch_rss_events() -> List[Dict]:
    response = requests.get(RSS_URL, timeout=10, verify=False, headers=HEADERS)
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


def get_today_status() -> str:
    """Return ongoing RSS events today (injected into system prompt)."""
    try:
        today = date.today()
        ongoing = [e for e in _fetch_rss_events() if e["start"] <= today <= e["end"]]
        if not ongoing:
            return ""
        titles = ", ".join(e["title"] for e in ongoing)
        return f"NOTE: Today ({today.strftime('%A, %B %d, %Y')}) the following events are ongoing: {titles}."
    except Exception:
        return ""


def get_upcoming_events() -> str:
    """Return upcoming and ongoing RSS events sorted by start date."""
    try:
        today = date.today()
        events = [e for e in _fetch_rss_events() if e["end"] >= today]
        if not events:
            return "No upcoming events found on the school calendar."

        events.sort(key=lambda e: e["start"])
        lines = ["Wells Middle School Events:\n"]
        for e in events:
            if e["start"] == e["end"]:
                date_str = e["start"].strftime("%A, %B %d, %Y")
            else:
                date_str = f"{e['start'].strftime('%B %d')} - {e['end'].strftime('%B %d, %Y')}"
            tag = " [ONGOING TODAY]" if e["start"] <= today <= e["end"] else ""
            line = f"- {date_str}: {e['title']}{tag}"
            if e["description"]:
                line += f" ({e['description']})"
            lines.append(line)
        return "\n".join(lines)
    except Exception as ex:
        return f"Error fetching calendar: {str(ex)}"

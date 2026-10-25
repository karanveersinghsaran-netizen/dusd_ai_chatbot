"""Counselor assignment lookup by last name.

Replaces LLM reasoning over scraped alphabetical range text (which fails
on edge cases — e.g. the model misreading `Smith` as falling in `Muu-Sam`
when it actually belongs in `San-Z`) with a deterministic Python string
comparison. Each school that assigns counselors by last name provides a
per-school data file at:

    data/schools/<id>/counselors.json

Schools without that file have no counselor-lookup tool registered on
the agent (see app/agent.py).

The data file lists each bucket by its START prefix only; the lookup
places a last name in the bucket whose start prefix is the largest one
that is lexicographically <= the last name (case-insensitive). The end
of each bucket is implicitly "right before the next bucket's start",
which matches how the schools publish these ranges on their websites.
"""
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "schools"


@lru_cache(maxsize=16)
def load_counselors(school_id: str) -> Optional[Dict[str, Any]]:
    """Load counselor assignments for a school. Returns None if no file
    exists for the given school."""
    path = DATA_DIR / school_id / "counselors.json"
    if not path.is_file():
        return None
    with path.open() as f:
        return json.load(f)


def has_counselor_assignments(school_id: str) -> bool:
    """True iff the school publishes counselor-by-last-name assignments."""
    return load_counselors(school_id) is not None


def lookup_counselor_by_last_name(
    school_id: str, last_name: str
) -> Optional[Dict[str, Any]]:
    """Resolve the counselor whose alphabetical bucket contains `last_name`.

    Returns a dict with the counselor's name, email, phone extension, main
    phone, role notes, and the assigned last-name range as published,
    plus the school's counseling-page URL. Returns None when the school has
    no data file or `last_name` is empty.

    Comparison is case-insensitive and uses Python's standard string order,
    the same order the published ranges imply."""
    data = load_counselors(school_id)
    if data is None:
        return None
    normalized_last_name = (last_name or "").strip().lower()
    if not normalized_last_name:
        return None

    counselors = data.get("counselors", {})
    buckets = data.get("assignments_by_last_name", [])

    # Sort buckets by start prefix so we can walk them in order and keep the
    # LAST start that is <= the name — that's the bucket the name falls in.
    sorted_buckets = sorted(
        ((bucket["start"].lower(), bucket["counselor_id"]) for bucket in buckets),
        key=lambda item: item[0],
    )
    matched_counselor_id: Optional[str] = None
    for start, counselor_id in sorted_buckets:
        if start <= normalized_last_name:
            matched_counselor_id = counselor_id
        else:
            break

    if matched_counselor_id is None:
        return None
    counselor = counselors.get(matched_counselor_id)
    if counselor is None:
        return None
    return {
        **counselor,
        "counselor_id": matched_counselor_id,
        "main_phone": data.get("phone_main"),
        "counseling_page_url": data.get("counseling_page_url"),
    }


def format_counselor_answer(counselor: Dict[str, Any], last_name: str) -> str:
    """Render a counselor record as a compact answer block the agent can
    paraphrase into its reply. Keeps the agent from inventing fields the
    data file doesn't carry (phone number, scheduling link, etc.)."""
    lines = [f"Counselor assignment for last name \"{last_name}\":"]
    lines.append(f"- Name: {counselor['name']}")
    lines.append(f"- Email: {counselor['email']}")
    phone_main = counselor.get("main_phone") or ""
    phone_ext = counselor.get("phone_ext") or ""
    if phone_main and phone_ext:
        lines.append(f"- Phone: {phone_main} ext. {phone_ext}")
    elif phone_main:
        lines.append(f"- Phone: {phone_main}")
    roles = counselor.get("roles") or []
    if roles:
        lines.append(f"- Role notes: {', '.join(roles)}")
    lines.append(f"- Assigned last-name range (as published): {counselor['last_name_range']}")
    url = counselor.get("counseling_page_url")
    if url:
        lines.append(f"- Counseling page: {url}")
    return "\n".join(lines)

"""Converts the DUSD 9-12 course catalog's raw Google-Docs markdown export
into department-chunked JSON, so app/services/course_catalog.py can serve one
department (or the front-matter overview) per tool call instead of dumping
the ~1MB source into the system prompt or re-parsing it live on every
request. Re-run this whenever the district publishes a new year's catalog.

Usage:
    python -m scripts.parse_course_catalog "path/to/source.md" \
        --school-year 2026-27 --district-id dusd \
        --out data/course_catalogs/dusd/2026_27.json
"""
import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Tuple

# Exact department heading text, in the order they appear in the catalog's
# own table of contents. The source doc renders each as its own one-row
# markdown table ("| Engineering |" or "|  English |" — inconsistent leading
# spacing between departments, hence matching by exact heading text rather
# than a generic regex).
DEPARTMENT_HEADINGS = [
    "Engineering",
    "English",
    "English Language Development (ELD)",
    "Family and Consumer Studies",
    "History-Social Science",
    "Mathematics",
    "Non-Departmental",
    "Performing Arts",
    "Physical Education",
    "Science",
    "Special Education Classes",
    "Tri-Valley ROP Classes",
    "Visual Arts",
    "World Languages",
]


def _clean(text: str) -> str:
    """Undo Google Docs' markdown-export escaping and one recurring OCR
    artifact (lowercase 'l' standing in for '1' in grade ranges like
    '9-l2') — both are export/transcription noise, not real content."""
    text = re.sub(r"\\([-().])", r"\1", text)
    text = re.sub(r"\bl2\b", "12", text)
    return text.strip()


def _heading_line_numbers(lines: List[str], headings: List[str]) -> Dict[str, int]:
    positions: Dict[str, int] = {}
    for i, line in enumerate(lines):
        stripped = line.strip()
        for heading in headings:
            if stripped in (f"| {heading} |", f"|  {heading} |"):
                positions[heading] = i
    missing = [h for h in headings if h not in positions]
    if missing:
        raise ValueError(f"Could not locate heading(s) in source doc: {missing}")
    return positions


_IMAGE_DATA_URI_RE = re.compile(r"^\[image\d+\]: <data:")


def parse(source_path: Path, headings: List[str] = DEPARTMENT_HEADINGS) -> dict:
    lines = source_path.read_text(encoding="utf-8").splitlines()
    # Reference-style image definitions (the doc's letterhead logo) land as
    # a base64 data: URI on a single line — often hundreds of KB, and
    # completely irrelevant to course content. Google Docs' markdown export
    # dumps these at the very end of the file regardless of where the image
    # is actually used, which would otherwise bloat whichever department
    # happens to be last (here: World Languages, ballooning ~20K chars to
    # ~770K).
    lines = [line for line in lines if not _IMAGE_DATA_URI_RE.match(line)]
    positions = _heading_line_numbers(lines, headings)
    ordered: List[Tuple[str, int]] = sorted(positions.items(), key=lambda kv: kv[1])

    overview_end = ordered[0][1]
    overview = _clean("\n".join(lines[:overview_end]))

    departments: Dict[str, str] = {}
    for idx, (name, start) in enumerate(ordered):
        end = ordered[idx + 1][1] if idx + 1 < len(ordered) else len(lines)
        departments[name] = _clean("\n".join(lines[start:end]))

    return {"overview": overview, "departments": departments}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--school-year", required=True, help="e.g. 2026-27")
    parser.add_argument("--district-id", required=True, help="e.g. dusd")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    data = parse(args.source)
    data["school_year"] = args.school_year
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"Wrote {args.out} — overview {len(data['overview'])} chars, "
        f"{len(data['departments'])} departments"
    )
    for name, text in data["departments"].items():
        print(f"  {name}: {len(text)} chars")


if __name__ == "__main__":
    main()

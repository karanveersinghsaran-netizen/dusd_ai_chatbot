"""Club roster service.

Some schools maintain their live club roster (meeting day/time/room, advisor)
in a Google Sheet rather than a static page on the school website — that
sheet is the source of truth, so we fetch it directly instead of scraping a
page that's liable to go stale. Requires the sheet (or the specific tab) to
be shared as "Anyone with the link can view".
"""
import csv
import io

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def get_club_list(sheet_csv_url: str) -> str:
    """Fetch and format a club roster from a Google Sheets CSV export URL.
    Expected columns: Club Name, Meeting Days, Meeting Time, Meeting Room,
    Advisor Name (President Name/Email columns are present in the sheet but
    omitted here — they're identifying info about individual students)."""
    try:
        response = requests.get(sheet_csv_url, timeout=10, headers=HEADERS)
        response.raise_for_status()
        reader = csv.DictReader(io.StringIO(response.text))

        lines = []
        for row in reader:
            name = (row.get("Club Name") or "").strip()
            if not name:
                continue
            days = (row.get("Meeting Days") or "").strip()
            time = (row.get("Meeting Time") or "").strip()
            room = (row.get("Meeting Room") or "").strip()
            advisor = (row.get("Advisor Name") or "").strip()

            schedule = ", ".join(part for part in [days, time] if part)
            line = f"- {name}"
            if schedule:
                line += f" — meets {schedule}"
            if room:
                line += f" in {room}"
            if advisor:
                line += f". Advisor: {advisor}"
            lines.append(line)

        if not lines:
            return "No club roster data found."
        return "Student Clubs:\n" + "\n".join(lines)
    except Exception as e:
        return f"Error fetching club list: {str(e)}"

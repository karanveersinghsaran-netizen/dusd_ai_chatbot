"""Unit tests for the club roster service (app/services/clubs.py)."""
from unittest.mock import MagicMock, patch

from app.services.clubs import get_club_list

SAMPLE_CSV = (
    "Club Name,President Name(s),President Email(s),Meeting Days,Meeting Time,Meeting Room,Advisor Name\n"
    "Chess Club,Jane Doe,doe1234@mydusd.org,1st and 3rd Thursday,Lunch,N-108,Chris Meyer\n"
    "Robotics Club,John Smith,smith5678@mydusd.org,Every Wednesday,Lunch,L-204,Neilson Vuong\n"
)


def test_get_club_list_formats_rows():
    with patch("app.services.clubs.requests.get") as mock_get:
        mock_get.return_value = MagicMock(text=SAMPLE_CSV, raise_for_status=lambda: None)
        result = get_club_list("https://example.com/sheet.csv")

    assert "Chess Club" in result
    assert "1st and 3rd Thursday, Lunch" in result
    assert "N-108" in result
    assert "Chris Meyer" in result
    assert "Robotics Club" in result


def test_get_club_list_omits_president_pii():
    with patch("app.services.clubs.requests.get") as mock_get:
        mock_get.return_value = MagicMock(text=SAMPLE_CSV, raise_for_status=lambda: None)
        result = get_club_list("https://example.com/sheet.csv")

    assert "Jane Doe" not in result
    assert "doe1234@mydusd.org" not in result


def test_get_club_list_skips_blank_rows():
    csv_with_blank = SAMPLE_CSV + ",,,,,,\n"
    with patch("app.services.clubs.requests.get") as mock_get:
        mock_get.return_value = MagicMock(text=csv_with_blank, raise_for_status=lambda: None)
        result = get_club_list("https://example.com/sheet.csv")

    assert result.count("- ") == 2


def test_get_club_list_handles_fetch_error():
    with patch("app.services.clubs.requests.get", side_effect=Exception("timeout")):
        result = get_club_list("https://example.com/sheet.csv")

    assert "Error fetching club list" in result

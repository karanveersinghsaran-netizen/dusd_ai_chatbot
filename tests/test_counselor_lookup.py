"""Tests for app.services.counselor_lookup.

The regression that motivated this module (bug reported 2026-10-24) was
the agent putting the last name "Smith" in Mr. Parker's bucket (Muu-Sam)
when it belongs in Mr. Calloway's (San-Z). That specific case is asserted
explicitly below; the rest of the tests cover the other DHS and EHS
boundaries so a future data-file edit can't silently break them.
"""
import pytest

from app.services import counselor_lookup
from app.services.counselor_lookup import (
    format_counselor_answer,
    has_counselor_assignments,
    load_counselors,
    lookup_counselor_by_last_name,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """`load_counselors` uses lru_cache; clear between tests so a file edit
    (or a monkeypatched DATA_DIR) is visible in the next call."""
    load_counselors.cache_clear()
    yield
    load_counselors.cache_clear()


class TestDHS:
    """Boundary coverage for DHS's five published buckets."""

    @pytest.mark.parametrize(
        "last_name,expected_counselor_id",
        [
            # The exact regression — Smith belongs to Calloway, not Parker.
            ("Smith", "calloway"),
            # Halket: A - Den
            ("Aaron", "halket"),
            ("Chen", "halket"),
            ("Den", "halket"),
            ("Denver", "halket"),      # Denver < Deo lexicographically
            # Luzzi: Deo - Kak
            ("Deo", "luzzi"),
            ("Fitzgerald", "luzzi"),
            ("Kak", "luzzi"),
            # Prado: Kal - Mut
            ("Kal", "prado"),
            ("Lee", "prado"),
            ("Mut", "prado"),
            # Parker: Muu - Sam
            ("Muu", "parker"),
            ("Nguyen", "parker"),
            ("Patel", "parker"),
            ("Sam", "parker"),
            # Calloway: San - Z
            ("San", "calloway"),
            ("Singh", "calloway"),
            ("Tran", "calloway"),
            ("Williams", "calloway"),
            ("Zumba", "calloway"),      # tail of the last bucket
        ],
    )
    def test_bucket_assignment(self, last_name, expected_counselor_id):
        result = lookup_counselor_by_last_name("dhs", last_name)
        assert result is not None, f"Expected a counselor for {last_name!r}, got None"
        assert result["counselor_id"] == expected_counselor_id, (
            f"{last_name!r} should fall in {expected_counselor_id}, got {result['counselor_id']}"
        )

    def test_case_insensitive(self):
        """A student will type their name in any case; all should route the same way."""
        for cased in ["smith", "SMITH", "sMiTh"]:
            assert lookup_counselor_by_last_name("dhs", cased)["counselor_id"] == "calloway"

    def test_whitespace_trimmed(self):
        assert lookup_counselor_by_last_name("dhs", "  Smith  ")["counselor_id"] == "calloway"

    def test_result_carries_contact_fields(self):
        """The agent's tool result must have everything it needs to answer
        without going back to scrape — name, email, phone, roles, range."""
        result = lookup_counselor_by_last_name("dhs", "Smith")
        assert result["name"] == "Mr. Eric Calloway"
        assert result["email"] == "callowayeric@dublinusd.org"
        assert result["phone_ext"] == "7021"
        assert result["main_phone"] == "(925) 833-3300"
        assert result["last_name_range"] == "San - Z"
        assert "NCAA Coordinator" in result["roles"]


class TestEHS:
    """Boundary coverage for Emerald High's five published buckets."""

    @pytest.mark.parametrize(
        "last_name,expected_counselor_id",
        [
            # Valone: A - Des
            ("Aaron", "valone"),
            ("Chen", "valone"),
            ("Des", "valone"),
            # Henning: Det - Kat
            ("Det", "henning"),
            ("Garcia", "henning"),
            ("Kat", "henning"),
            # Ureno: Kau - Neg
            ("Kau", "ureno"),
            ("Lee", "ureno"),
            ("Neg", "ureno"),
            # Nandakishore: Neh - Sind
            ("Neh", "nandakishore"),
            ("Patel", "nandakishore"),
            ("Rodriguez", "nandakishore"),
            ("Sind", "nandakishore"),
            # Martin: Sine - Z
            ("Sine", "martin"),
            ("Smith", "martin"),         # Smith belongs here too for EHS
            ("Williams", "martin"),
            ("Zhang", "martin"),
        ],
    )
    def test_bucket_assignment(self, last_name, expected_counselor_id):
        result = lookup_counselor_by_last_name("emerald", last_name)
        assert result is not None
        assert result["counselor_id"] == expected_counselor_id

    def test_result_carries_contact_fields(self):
        result = lookup_counselor_by_last_name("emerald", "Smith")
        assert result["name"] == "Angela Martin"
        assert result["email"] == "martinangela@dublinusd.org"
        assert result["phone_ext"] == "4822"
        assert result["main_phone"] == "925-551-4040"
        assert result["last_name_range"] == "Sine - Z"


class TestEdgeCases:
    def test_school_without_counselor_data(self):
        """A school with no counselors.json (e.g. a middle school) returns None,
        which lets the agent fall back to the scrape path cleanly."""
        assert lookup_counselor_by_last_name("wells", "Smith") is None
        assert lookup_counselor_by_last_name("fallon", "Smith") is None
        assert has_counselor_assignments("wells") is False

    def test_dhs_has_counselor_assignments(self):
        assert has_counselor_assignments("dhs") is True

    def test_unknown_school_returns_none(self):
        assert lookup_counselor_by_last_name("not-a-real-school", "Smith") is None
        assert has_counselor_assignments("not-a-real-school") is False

    def test_empty_last_name_returns_none(self):
        assert lookup_counselor_by_last_name("dhs", "") is None
        assert lookup_counselor_by_last_name("dhs", "   ") is None
        assert lookup_counselor_by_last_name("dhs", None) is None  # type: ignore[arg-type]


class TestFormatAnswer:
    """Rendered answer block the agent incorporates into its reply."""

    def test_includes_all_fields(self):
        counselor = lookup_counselor_by_last_name("dhs", "Smith")
        text = format_counselor_answer(counselor, "Smith")
        assert "Mr. Eric Calloway" in text
        assert "callowayeric@dublinusd.org" in text
        assert "(925) 833-3300" in text
        assert "7021" in text
        assert "NCAA Coordinator" in text
        assert "San - Z" in text
        assert "Smith" in text

    def test_omits_roles_when_empty(self):
        """Halket has no role notes; the block shouldn't carry an empty line."""
        counselor = lookup_counselor_by_last_name("dhs", "Aaron")
        text = format_counselor_answer(counselor, "Aaron")
        assert "Role notes:" not in text

    def test_includes_roles_when_present(self):
        counselor = lookup_counselor_by_last_name("dhs", "Patel")  # Parker: Muu-Sam
        text = format_counselor_answer(counselor, "Patel")
        assert "Co-Lead Counselor" in text
        assert "AVID" in text


class TestDataFiles:
    """Lightweight schema checks on the on-disk JSON — a typo in a bucket
    boundary would silently misroute students, so pin the file structure."""

    @pytest.mark.parametrize("school_id", ["dhs", "emerald"])
    def test_file_shape(self, school_id):
        data = load_counselors(school_id)
        assert data is not None
        assert "phone_main" in data
        assert "assignments_by_last_name" in data
        assert "counselors" in data
        # Every bucket's counselor_id must resolve.
        for bucket in data["assignments_by_last_name"]:
            assert bucket["counselor_id"] in data["counselors"], (
                f"{school_id}: bucket {bucket!r} names unknown counselor"
            )
        # Every counselor must have the fields the formatter prints.
        for cid, counselor in data["counselors"].items():
            for required in ("name", "email", "phone_ext", "last_name_range", "roles"):
                assert required in counselor, f"{school_id}:{cid} missing {required}"

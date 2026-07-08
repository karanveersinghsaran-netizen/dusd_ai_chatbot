"""Unit tests for signed session-id issuing/verification."""
from unittest.mock import patch

import pytest

from app.security.sessions import issue_session_id, verify_session_id

KEY = "test-signing-key"


def test_issue_then_verify_roundtrip():
    session_id, cookie_value = issue_session_id(KEY)
    assert verify_session_id(cookie_value, KEY) == session_id


def test_verify_rejects_tampered_signature():
    session_id, cookie_value = issue_session_id(KEY)
    sid, sig = cookie_value.rsplit(".", 1)
    tampered = f"{sid}.{'0' if sig[0] != '0' else '1'}{sig[1:]}"
    assert verify_session_id(tampered, KEY) is None


def test_verify_rejects_tampered_session_id():
    session_id, cookie_value = issue_session_id(KEY)
    sid, sig = cookie_value.rsplit(".", 1)
    tampered = f"{sid}extra.{sig}"
    assert verify_session_id(tampered, KEY) is None


@pytest.mark.parametrize("malformed", ["", "no-dot-here", "."])
def test_verify_rejects_malformed_cookie(malformed):
    assert verify_session_id(malformed, KEY) is None


def test_verify_rejects_wrong_key():
    _, cookie_value = issue_session_id(KEY)
    assert verify_session_id(cookie_value, "a-different-key") is None


def test_issue_session_id_raises_when_key_unset():
    with patch("app.security.sessions.config.SESSION_SIGNING_KEY", None):
        with pytest.raises(RuntimeError):
            issue_session_id()


def test_two_issued_ids_are_unique():
    first, _ = issue_session_id(KEY)
    second, _ = issue_session_id(KEY)
    assert first != second

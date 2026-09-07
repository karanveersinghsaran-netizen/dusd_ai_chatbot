"""Unit tests for #51's identity resolution: a valid chatbox token's user_id
wins when present, falls back to the session cookie otherwise. /chat,
/feedback/thanks, and /feedback/report all go through resolve_user_id(), so
it's exercised here directly rather than only indirectly via main.py's
TestClient (see tests/test_main.py for the end-to-end versions)."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response

from app.security.chatbox_token import issue_chatbox_token
from app.security.identity import SESSION_COOKIE_MAX_AGE, resolve_user_id
from app.security.sessions import issue_session_id

SESSION_KEY = "test-session-key"
CHATBOX_KEY = "test-chatbox-key"


@pytest.fixture(autouse=True)
def _signing_keys():
    with patch("app.config.SESSION_SIGNING_KEY", SESSION_KEY), \
         patch("app.config.CHATBOX_TOKEN_SIGNING_KEY", CHATBOX_KEY):
        yield


# ── TTL (#51: cookies persist 5d) ────────────────────────────────────────────

def test_session_cookie_max_age_is_5_days():
    assert SESSION_COOKIE_MAX_AGE == 5 * 24 * 60 * 60


# ── no token: cookie-only fallback (unchanged pre-#51 behavior) ─────────────

def test_no_token_no_cookie_mints_fresh_session_id():
    response = Response()
    user_id = resolve_user_id(None, None, response)
    assert user_id
    assert "wms_session=" in response.headers.get("set-cookie", "")


def test_no_token_valid_cookie_reuses_session_id():
    session_id, cookie_value = issue_session_id(SESSION_KEY)
    resolved = resolve_user_id(None, cookie_value, Response())
    assert resolved == session_id


def test_no_token_invalid_cookie_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        resolve_user_id(None, "garbage.tampered", Response())
    assert exc_info.value.status_code == 401


# ── valid token: wins over cookie ────────────────────────────────────────────

def test_valid_token_returns_token_user_id_ignoring_cookie():
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, user_id="admin-1")
    session_id, cookie_value = issue_session_id(SESSION_KEY)
    resolved = resolve_user_id(token, cookie_value, Response())
    assert resolved == "admin-1"
    assert resolved != session_id


def test_valid_token_with_invalid_cookie_does_not_raise():
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, user_id="admin-1")
    response = Response()
    resolved = resolve_user_id(token, "garbage.tampered", response)
    assert resolved == "admin-1"
    assert "wms_session=" in response.headers.get("set-cookie", "")


def test_valid_token_with_no_cookie_still_sets_a_fresh_one():
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, user_id="admin-1")
    response = Response()
    resolved = resolve_user_id(token, None, response)
    assert resolved == "admin-1"
    assert "wms_session=" in response.headers.get("set-cookie", "")


def test_expired_token_falls_back_to_cookie_session_id():
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, user_id="admin-1", days_valid=-1)
    session_id, cookie_value = issue_session_id(SESSION_KEY)
    resolved = resolve_user_id(token, cookie_value, Response())
    assert resolved == session_id


# ── generic (mass-distribution) token: never carries identity ──────────────

def test_generic_token_falls_back_to_cookie_not_marker():
    """A generic token still proves access, but must never leak the reserved
    marker out as if it were a real identity — each visitor's own cookie
    resolves it instead, same as if no token were present."""
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, generic=True)
    session_id, cookie_value = issue_session_id(SESSION_KEY)
    resolved = resolve_user_id(token, cookie_value, Response())
    assert resolved == session_id


def test_generic_token_no_cookie_mints_a_fresh_session_id():
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, generic=True)
    response = Response()
    resolved = resolve_user_id(token, None, response)
    assert resolved
    assert "wms_session=" in response.headers.get("set-cookie", "")


def test_generic_token_with_invalid_cookie_still_raises_401():
    """Unlike a real personal token (which proves identity on its own and so
    tolerates a bad cookie), a generic token proves nothing about who this
    is — a tampered cookie is the only identity signal available, so it must
    still 401 exactly like the no-token case."""
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, generic=True)
    with pytest.raises(HTTPException) as exc_info:
        resolve_user_id(token, "garbage.tampered", Response())
    assert exc_info.value.status_code == 401


def test_generic_token_two_visitors_get_different_identities():
    """The actual point of a generic token: many people opening the SAME
    link must NOT collide into one shared identity — each visitor's own
    (absent, in this simulation) cookie mints its own fresh session id."""
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, generic=True)
    parent_a = resolve_user_id(token, None, Response())
    parent_b = resolve_user_id(token, None, Response())
    assert parent_a != parent_b


# ── the actual #51 scenario: same token, separate cookie jars ──────────────

def test_same_token_resolves_to_same_user_id_across_different_cookie_jars():
    """Simulates a Safari tab and a home-screen-installed PWA opened from the
    same link: two separate requests with no cookie shared between them
    (different/empty cookie jars) but the SAME token — must land on the SAME
    Redis bucket."""
    token = issue_chatbox_token(signing_key=CHATBOX_KEY, user_id="admin-1")

    safari_user_id = resolve_user_id(token, None, Response())
    pwa_user_id = resolve_user_id(token, None, Response())

    assert safari_user_id == pwa_user_id == "admin-1"

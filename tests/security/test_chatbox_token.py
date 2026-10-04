"""Unit tests for signed, self-expiring /chatbox access tokens."""
from unittest.mock import patch

import pytest

from app.security.chatbox_token import (
    GENERIC_USER_MARKER,
    TOKEN_EXPIRED,
    TOKEN_MALFORMED,
    TOKEN_MISSING,
    classify_chatbox_token,
    decode_chatbox_token,
    issue_chatbox_token,
    verify_chatbox_token,
)

KEY = "test-signing-key"


def test_issue_then_verify_roundtrip():
    token = issue_chatbox_token(signing_key=KEY)
    assert verify_chatbox_token(token, KEY) is True


def test_verify_rejects_tampered_signature():
    token = issue_chatbox_token(signing_key=KEY)
    payload, sig = token.rsplit(".", 1)
    tampered = f"{payload}.{'0' if sig[0] != '0' else '1'}{sig[1:]}"
    assert verify_chatbox_token(tampered, KEY) is False


def test_verify_rejects_tampered_expiry():
    token = issue_chatbox_token(signing_key=KEY)
    expires_at, user_id, sig = token.split(".", 2)
    tampered = f"{int(expires_at) + 999999}.{user_id}.{sig}"
    assert verify_chatbox_token(tampered, KEY) is False


def test_verify_rejects_tampered_user_id():
    token = issue_chatbox_token(signing_key=KEY, user_id="admin-1")
    expires_at, user_id, sig = token.split(".", 2)
    tampered = f"{expires_at}.admin-2.{sig}"
    assert verify_chatbox_token(tampered, KEY) is False


@pytest.mark.parametrize("malformed", ["", "no-dot-here", ".", "1.2"])
def test_verify_rejects_malformed_token(malformed):
    assert verify_chatbox_token(malformed, KEY) is False


def test_verify_rejects_wrong_key():
    token = issue_chatbox_token(signing_key=KEY)
    assert verify_chatbox_token(token, "a-different-key") is False


def test_verify_rejects_expired_token():
    token = issue_chatbox_token(days_valid=-1, signing_key=KEY)
    assert verify_chatbox_token(token, KEY) is False


def test_issue_chatbox_token_raises_when_key_unset():
    with patch("app.security.chatbox_token.config.CHATBOX_TOKEN_SIGNING_KEY", None):
        with pytest.raises(RuntimeError):
            issue_chatbox_token()


def test_issue_rejects_user_id_containing_dot():
    with pytest.raises(ValueError):
        issue_chatbox_token(signing_key=KEY, user_id="bad.id")


# ── user_id claim (#51) ──────────────────────────────────────────────────────

def test_issue_embeds_provided_user_id():
    token = issue_chatbox_token(signing_key=KEY, user_id="admin-1")
    payload = decode_chatbox_token(token, KEY)
    assert payload is not None
    assert payload.user_id == "admin-1"


def test_issue_auto_generates_user_id_when_omitted():
    token = issue_chatbox_token(signing_key=KEY)
    payload = decode_chatbox_token(token, KEY)
    assert payload is not None
    assert payload.user_id  # non-empty


def test_issue_auto_generated_user_ids_are_unique():
    token_a = issue_chatbox_token(signing_key=KEY)
    token_b = issue_chatbox_token(signing_key=KEY)
    assert decode_chatbox_token(token_a, KEY).user_id != decode_chatbox_token(token_b, KEY).user_id


def test_same_user_id_yields_same_decoded_identity_across_reissues():
    """Re-issuing a link (e.g. after the old token expired) with the same
    user_id must resolve to the same identity — this is what lets an admin
    get a fresh link without losing their Redis conversation history."""
    token_1 = issue_chatbox_token(signing_key=KEY, user_id="admin-1", days_valid=1)
    token_2 = issue_chatbox_token(signing_key=KEY, user_id="admin-1", days_valid=30)
    assert decode_chatbox_token(token_1, KEY).user_id == decode_chatbox_token(token_2, KEY).user_id == "admin-1"


# ── generic (mass-distribution) tokens (#51 follow-up) ──────────────────────

def test_issue_generic_embeds_reserved_marker():
    token = issue_chatbox_token(signing_key=KEY, generic=True)
    payload = decode_chatbox_token(token, KEY)
    assert payload is not None
    assert payload.user_id == GENERIC_USER_MARKER


def test_issue_generic_still_verifies_and_gates_access():
    """A generic token is still a real, signed, expiring token — it just
    doesn't carry personal identity. The /chatbox and /manifest.webmanifest
    gates only check validity, so they work unchanged."""
    token = issue_chatbox_token(signing_key=KEY, generic=True)
    assert verify_chatbox_token(token, KEY) is True


def test_issue_rejects_generic_and_user_id_together():
    with pytest.raises(ValueError):
        issue_chatbox_token(signing_key=KEY, generic=True, user_id="admin-1")


def test_issue_rejects_user_id_equal_to_generic_marker():
    with pytest.raises(ValueError):
        issue_chatbox_token(signing_key=KEY, user_id=GENERIC_USER_MARKER)


def test_decode_returns_none_for_invalid_token():
    assert decode_chatbox_token("garbage", KEY) is None


def test_decode_returns_none_for_expired_token():
    token = issue_chatbox_token(signing_key=KEY, user_id="admin-1", days_valid=-1)
    assert decode_chatbox_token(token, KEY) is None


# ── classify_chatbox_token: WHY a link was rejected ─────────────────────────

def test_classify_returns_none_for_a_valid_token():
    assert classify_chatbox_token(issue_chatbox_token(signing_key=KEY), KEY) is None


def test_classify_reports_expired_separately_from_malformed():
    """The distinction the error page depends on: a lapsed link and a
    damaged one need opposite instructions."""
    expired = issue_chatbox_token(signing_key=KEY, days_valid=-1)
    assert classify_chatbox_token(expired, KEY) == TOKEN_EXPIRED
    assert classify_chatbox_token("garbage", KEY) == TOKEN_MALFORMED


@pytest.mark.parametrize("token", ["", None])
def test_classify_reports_missing_for_absent_token(token):
    assert classify_chatbox_token(token, KEY) == TOKEN_MISSING


def test_classify_reports_truncated_token_as_malformed():
    token = issue_chatbox_token(signing_key=KEY)
    assert classify_chatbox_token(token[:-8], KEY) == TOKEN_MALFORMED


def test_classify_reports_markdown_escaped_generic_marker_as_malformed():
    """A generic token's user_id is the literal "*"; written in markdown it
    becomes "\\*", breaking the signature. This is the case that produced a
    misleading "expired" page in practice."""
    token = issue_chatbox_token(signing_key=KEY, generic=True)
    assert classify_chatbox_token(token.replace("*", chr(92) + "*"), KEY) == TOKEN_MALFORMED


def test_classify_reports_wrong_key_as_malformed():
    """A token signed for another environment isn't expired — it just can't
    be verified here."""
    token = issue_chatbox_token(signing_key="other-key")
    assert classify_chatbox_token(token, KEY) == TOKEN_MALFORMED


def test_classify_reports_expiry_extension_attempt_as_malformed():
    """Bumping the embedded expiry invalidates the signature, so a forged
    extension is malformed — NOT expired, and certainly not valid."""
    token = issue_chatbox_token(signing_key=KEY, days_valid=-1)
    _, user_id, signature = token.split(".", 2)
    forged = f"9999999999.{user_id}.{signature}"
    assert classify_chatbox_token(forged, KEY) == TOKEN_MALFORMED


def test_classify_and_verify_never_disagree():
    """Both read the same decode, so "valid" means the same thing to the
    gate and to the page it renders on rejection."""
    tokens = [
        issue_chatbox_token(signing_key=KEY),
        issue_chatbox_token(signing_key=KEY, generic=True),
        issue_chatbox_token(signing_key=KEY, days_valid=-1),
        "garbage",
        "a.b.c",
    ]
    for token in tokens:
        assert verify_chatbox_token(token, KEY) is (classify_chatbox_token(token, KEY) is None)

"""Unit tests for signed, self-expiring /chatbox access tokens."""
from unittest.mock import patch

import pytest

from app.security.chatbox_token import decode_chatbox_token, issue_chatbox_token, verify_chatbox_token

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


def test_decode_returns_none_for_invalid_token():
    assert decode_chatbox_token("garbage", KEY) is None


def test_decode_returns_none_for_expired_token():
    token = issue_chatbox_token(signing_key=KEY, user_id="admin-1", days_valid=-1)
    assert decode_chatbox_token(token, KEY) is None

"""Unit tests for signed, self-expiring /chatbox access tokens."""
from unittest.mock import patch

import pytest

from app.security.chatbox_token import issue_chatbox_token, verify_chatbox_token

KEY = "test-signing-key"


def test_issue_then_verify_roundtrip():
    token = issue_chatbox_token(signing_key=KEY)
    assert verify_chatbox_token(token, KEY) is True


def test_verify_rejects_tampered_signature():
    token = issue_chatbox_token(signing_key=KEY)
    expires_at, sig = token.rsplit(".", 1)
    tampered = f"{expires_at}.{'0' if sig[0] != '0' else '1'}{sig[1:]}"
    assert verify_chatbox_token(tampered, KEY) is False


def test_verify_rejects_tampered_expiry():
    token = issue_chatbox_token(signing_key=KEY)
    expires_at, sig = token.rsplit(".", 1)
    tampered = f"{int(expires_at) + 999999}.{sig}"
    assert verify_chatbox_token(tampered, KEY) is False


@pytest.mark.parametrize("malformed", ["", "no-dot-here", "."])
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

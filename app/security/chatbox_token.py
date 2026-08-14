import hashlib
import hmac
import time
from typing import Optional, Union

from app import config

DEFAULT_VALID_DAYS = 7


def issue_chatbox_token(
    days_valid: int = DEFAULT_VALID_DAYS,
    signing_key: Optional[Union[str, bytes]] = None,
) -> str:
    """Mints a token encoding an expiry timestamp, signed so it can't be
    forged or extended by a client. Format: "<expires_at_unix>.<hmac_hex>"."""
    expires_at = int(time.time()) + days_valid * 86400
    signature = _sign(str(expires_at), _resolve_key(signing_key))
    return f"{expires_at}.{signature}"


def verify_chatbox_token(
    token: str,
    signing_key: Optional[Union[str, bytes]] = None,
) -> bool:
    """True if token has a valid signature and has not expired."""
    try:
        expires_at_str, signature = token.rsplit(".", 1)
    except (ValueError, AttributeError):
        return False

    if not expires_at_str or not signature:
        return False

    expected = _sign(expires_at_str, _resolve_key(signing_key))
    if not hmac.compare_digest(expected, signature):
        return False

    try:
        expires_at = int(expires_at_str)
    except ValueError:
        return False

    return expires_at > int(time.time())


def _sign(expires_at_str: str, key: bytes) -> str:
    return hmac.new(key, expires_at_str.encode(), hashlib.sha256).hexdigest()


def _resolve_key(signing_key: Optional[Union[str, bytes]]) -> bytes:
    key = signing_key if signing_key is not None else config.CHATBOX_TOKEN_SIGNING_KEY
    if not key:
        raise RuntimeError("CHATBOX_TOKEN_SIGNING_KEY is not configured")
    return key.encode() if isinstance(key, str) else key

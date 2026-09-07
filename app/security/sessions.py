import hashlib
import hmac
import secrets
from typing import Optional, Union

from app import config


def issue_session_id(signing_key: Optional[Union[str, bytes]] = None) -> tuple[str, str]:
    """Mints a new random session id and returns (session_id, signed_cookie_value)."""
    session_id = secrets.token_urlsafe(32)
    return session_id, sign_session_id(session_id, signing_key)


def sign_session_id(session_id: str, signing_key: Optional[Union[str, bytes]] = None) -> str:
    """Returns the signed cookie value for an EXISTING session id, without
    minting a new one. Used to refresh a session cookie's expiry (#51: 'push
    the cookie's max-age out on every active request so it doesn't die from
    inactivity') while keeping the same session_id — re-signing with
    issue_session_id() instead would rotate the id and orphan the Redis
    history tied to the old one."""
    signature = _sign(session_id, _resolve_key(signing_key))
    return f"{session_id}.{signature}"


def verify_session_id(cookie_value: str, signing_key: Optional[Union[str, bytes]] = None) -> Optional[str]:
    """Returns the bare session id if the cookie's signature is valid, else None."""
    try:
        session_id, signature = cookie_value.rsplit(".", 1)
    except (ValueError, AttributeError):
        return None

    if not session_id or not signature:
        return None

    expected = _sign(session_id, _resolve_key(signing_key))
    if not hmac.compare_digest(expected, signature):
        return None
    return session_id


def _sign(session_id: str, key: bytes) -> str:
    return hmac.new(key, session_id.encode(), hashlib.sha256).hexdigest()


def _resolve_key(signing_key: Optional[Union[str, bytes]]) -> bytes:
    key = signing_key if signing_key is not None else config.SESSION_SIGNING_KEY
    if not key:
        raise RuntimeError("SESSION_SIGNING_KEY is not configured")
    return key.encode() if isinstance(key, str) else key

import hashlib
import hmac
import secrets
import time
from typing import NamedTuple, Optional, Union

from app import config

DEFAULT_VALID_DAYS = 7


class ChatboxTokenPayload(NamedTuple):
    expires_at: int
    user_id: str


def issue_chatbox_token(
    days_valid: int = DEFAULT_VALID_DAYS,
    signing_key: Optional[Union[str, bytes]] = None,
    user_id: Optional[str] = None,
) -> str:
    """Mints a token encoding an expiry timestamp and a stable user_id, signed
    so neither can be forged or extended by a client. Format:
    "<expires_at_unix>.<user_id>.<hmac_hex>".

    The embedded user_id (#51) is what gives a chatbox link a persistent
    identity: the token — not a cookie — rides along in the URL (and the PWA
    manifest's start_url), so a Safari tab and a home-screen-installed PWA
    opened from the SAME link resolve to the SAME user_id and share Redis
    history, even though iOS gives them separate, isolated cookie jars.

    Auto-generates a random user_id when one isn't supplied, which is the
    common case (scripts/generate_chatbox_token.py minting a brand new
    preview link). Pass an explicit user_id to mint a REPLACEMENT link for
    an existing identity — e.g. re-issuing an admin's link after their old
    token expired, without orphaning their conversation history.
    """
    if user_id is not None and "." in user_id:
        raise ValueError("user_id must not contain '.'")
    expires_at = int(time.time()) + days_valid * 86400
    resolved_user_id = user_id or secrets.token_urlsafe(16)
    payload_str = f"{expires_at}.{resolved_user_id}"
    signature = _sign(payload_str, _resolve_key(signing_key))
    return f"{payload_str}.{signature}"


def verify_chatbox_token(
    token: str,
    signing_key: Optional[Union[str, bytes]] = None,
) -> bool:
    """True if token has a valid signature and has not expired."""
    return decode_chatbox_token(token, signing_key) is not None


def decode_chatbox_token(
    token: str,
    signing_key: Optional[Union[str, bytes]] = None,
) -> Optional[ChatboxTokenPayload]:
    """Returns the decoded (expires_at, user_id) payload if the token's
    signature is valid and it hasn't expired, else None.

    This is the piece #51's persistent identity relies on: /chat (and any
    future endpoint, e.g. #72/#73's history-management work) can call this
    directly to recover the token's stable user_id instead of just checking
    the token is valid."""
    try:
        expires_at_str, user_id, signature = token.split(".", 2)
    except (ValueError, AttributeError):
        return None

    if not expires_at_str or not user_id or not signature:
        return None

    payload_str = f"{expires_at_str}.{user_id}"
    expected = _sign(payload_str, _resolve_key(signing_key))
    if not hmac.compare_digest(expected, signature):
        return None

    try:
        expires_at = int(expires_at_str)
    except ValueError:
        return None

    if expires_at <= int(time.time()):
        return None

    return ChatboxTokenPayload(expires_at=expires_at, user_id=user_id)


def _sign(payload_str: str, key: bytes) -> str:
    return hmac.new(key, payload_str.encode(), hashlib.sha256).hexdigest()


def _resolve_key(signing_key: Optional[Union[str, bytes]]) -> bytes:
    key = signing_key if signing_key is not None else config.CHATBOX_TOKEN_SIGNING_KEY
    if not key:
        raise RuntimeError("CHATBOX_TOKEN_SIGNING_KEY is not configured")
    return key.encode() if isinstance(key, str) else key

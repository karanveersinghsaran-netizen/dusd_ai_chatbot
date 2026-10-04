import hashlib
import hmac
import secrets
import time
from typing import NamedTuple, Optional, Union

from app import config

DEFAULT_VALID_DAYS = 7

# Reserved user_id value marking a token as "access-only" — see issue_chatbox_token's
# generic= param. Never producible by secrets.token_urlsafe(16) (which only ever
# emits multi-character base64url strings), so it can't collide with a real one.
GENERIC_USER_MARKER = "*"

# Why a chatbox link was rejected — see classify_chatbox_token.
TOKEN_MISSING = "missing"
TOKEN_MALFORMED = "malformed"
TOKEN_EXPIRED = "expired"


class ChatboxTokenPayload(NamedTuple):
    expires_at: int
    user_id: str


def issue_chatbox_token(
    days_valid: int = DEFAULT_VALID_DAYS,
    signing_key: Optional[Union[str, bytes]] = None,
    user_id: Optional[str] = None,
    generic: bool = False,
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

    Pass generic=True instead for a link meant to be distributed to many
    people at once (e.g. one link shared with every parent at a school so
    they can each install it as a PWA). It still gates /chatbox and
    /manifest.webmanifest like any other token, but deliberately carries no
    personal identity — app.security.identity.resolve_user_id recognizes
    GENERIC_USER_MARKER and falls back to each visitor's own per-device
    session cookie instead, so everyone who opens the same link still gets
    their own private conversation (at the cost of the Safari-tab/installed-
    PWA continuity a personal token provides — acceptable here since mass
    distribution and per-person identity are fundamentally in tension).
    Mutually exclusive with user_id.
    """
    if generic and user_id is not None:
        raise ValueError("generic and user_id are mutually exclusive")
    if user_id is not None:
        if "." in user_id:
            raise ValueError("user_id must not contain '.'")
        if user_id == GENERIC_USER_MARKER:
            raise ValueError(f"user_id must not be the reserved generic marker {GENERIC_USER_MARKER!r}")
    expires_at = int(time.time()) + days_valid * 86400
    resolved_user_id = GENERIC_USER_MARKER if generic else (user_id or secrets.token_urlsafe(16))
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
    return _decode(token, signing_key)[0]


def classify_chatbox_token(
    token: Optional[str],
    signing_key: Optional[Union[str, bytes]] = None,
) -> Optional[str]:
    """None if the token is valid and current, else WHY it was rejected:
    TOKEN_MISSING, TOKEN_MALFORMED, or TOKEN_EXPIRED.

    decode_chatbox_token collapses all three into None, which is exactly
    right for gating a request but wrong for the page shown afterwards. A
    link that lapsed and a link that arrived damaged (truncated by a chat
    client, mangled by markdown escaping, copied without its last line)
    need opposite instructions — "ask for a fresh link" vs "you already
    have a good link, copy all of it" — and rendering "expired" for both
    sends people chasing the wrong problem.

    Reporting EXPIRED does confirm that a signature verified, where
    MALFORMED doesn't. That's not a useful oracle: HMAC-SHA256 gives an
    attacker no way to search for a valid signature, and the only person
    who can elicit EXPIRED is someone already holding a legitimately-signed
    token, who therefore learns nothing new about it."""
    if not token:
        return TOKEN_MISSING
    return _decode(token, signing_key)[1]


def _decode(
    token: str,
    signing_key: Optional[Union[str, bytes]] = None,
) -> tuple[Optional[ChatboxTokenPayload], Optional[str]]:
    """(payload, None) when valid, else (None, rejection reason). The single
    implementation behind both decode_chatbox_token and
    classify_chatbox_token, so the two can never disagree about whether a
    given token passes."""
    try:
        expires_at_str, user_id, signature = token.split(".", 2)
    except (ValueError, AttributeError):
        return None, TOKEN_MALFORMED

    if not expires_at_str or not user_id or not signature:
        return None, TOKEN_MALFORMED

    payload_str = f"{expires_at_str}.{user_id}"
    expected = _sign(payload_str, _resolve_key(signing_key))
    if not hmac.compare_digest(expected, signature):
        return None, TOKEN_MALFORMED

    try:
        expires_at = int(expires_at_str)
    except ValueError:
        return None, TOKEN_MALFORMED

    if expires_at <= int(time.time()):
        return None, TOKEN_EXPIRED

    return ChatboxTokenPayload(expires_at=expires_at, user_id=user_id), None


def _sign(payload_str: str, key: bytes) -> str:
    return hmac.new(key, payload_str.encode(), hashlib.sha256).hexdigest()


def _resolve_key(signing_key: Optional[Union[str, bytes]]) -> bytes:
    key = signing_key if signing_key is not None else config.CHATBOX_TOKEN_SIGNING_KEY
    if not key:
        raise RuntimeError("CHATBOX_TOKEN_SIGNING_KEY is not configured")
    return key.encode() if isinstance(key, str) else key

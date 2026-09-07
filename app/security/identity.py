"""Resolves the stable identifier used to key Redis state (conversation
history, feedback flags, and any future per-user state) for a request (#51).

Two independent identity sources exist:
  - a signed `wms_session` cookie — first-party, but scoped to a single
    cookie jar
  - a signed chatbox token embedded in the /chatbox URL (?token=...,
    app/security/chatbox_token.py) — travels with the link itself

The cookie alone breaks down in exactly the two ways #51 describes: iOS
Safari's ITP can clear it or it can simply expire, and installing the
chatbox as a home-screen PWA gives the standalone WebView its own cookie
jar, isolated from the Safari tab it was installed from — so the same
person ends up with two different session_ids (and two "different"
conversations) for what is, to them, the same chat. The chatbox token
survives both, since it's baked into the URL (and forwarded into the PWA
manifest's start_url — see main.py's /manifest.webmanifest) rather than
stored in either cookie jar.

`resolve_user_id()` is the single place that decides between the two, so
/chat and future endpoints (#72 "clear conversation", #73 "restore chat
history") all key Redis the same way. It prefers a valid token's user_id
when present, and falls back to the session cookie otherwise — which keeps
the plain iframe embed (no token, cookie only) working exactly as it did
before this feature. Note the caveat from #51: the token IS the identity
here, so anyone with the link shares that user's history. Acceptable during
the preview-link phase (each admin gets their own link); real auth is out
of scope for #51.
"""
from typing import Optional

from fastapi import HTTPException, Response

from app.security.chatbox_token import decode_chatbox_token
from app.security.sessions import issue_session_id, sign_session_id, verify_session_id

SESSION_COOKIE_NAME = "wms_session"
SESSION_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30d, refreshed on every request below


def resolve_user_id(
    token: Optional[str],
    wms_session: Optional[str],
    response: Response,
) -> str:
    """Returns the identifier to key Redis state on for this request, and
    sets/refreshes the `wms_session` cookie as a side effect regardless of
    which identity source wins (so cookie identity stays warm for any
    future request that arrives without a token).

    Raises 401 if no usable identity is found and a `wms_session` cookie WAS
    presented but fails signature verification — unless a valid token
    already resolved identity, in which case a bad/missing cookie is simply
    replaced rather than blocking the request, since the token is already
    sufficient proof of identity.
    """
    if token:
        payload = decode_chatbox_token(token)
        if payload is not None:
            session_id = _verify_cookie(wms_session) or issue_session_id()[0]
            _set_session_cookie(session_id, response)
            return payload.user_id

    session_id = _verify_cookie(wms_session)
    if session_id is None:
        if wms_session is not None:
            raise HTTPException(status_code=401, detail="Invalid session cookie")
        session_id = issue_session_id()[0]
    _set_session_cookie(session_id, response)
    return session_id


def _verify_cookie(wms_session: Optional[str]) -> Optional[str]:
    """Bare session id from a validly-signed cookie, or None if missing/invalid."""
    return verify_session_id(wms_session) if wms_session else None


def _set_session_cookie(session_id: str, response: Response) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=sign_session_id(session_id),
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_COOKIE_MAX_AGE,
    )

"""Shared security dependencies for HTTP endpoints: rate limiting and a
request body size cap. Kept separate from app.security.sessions so that
transport-layer concerns don't mix with cookie signing logic."""
from fastapi import HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.security.sessions import verify_session_id

MAX_BODY_BYTES = 2048


def session_or_ip_key(request: Request) -> str:
    """Rate-limit key: the verified session id if the request carries a valid
    signed cookie, else the client IP. Falls back to IP for first-time
    visitors (no cookie yet) and for forged/garbage cookie values, so a
    forged cookie can't be used to dodge the per-session limit — the
    per-IP limiter still applies in that case."""
    cookie = request.cookies.get("wms_session")
    if cookie:
        session_id = verify_session_id(cookie)
        if session_id:
            return f"session:{session_id}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=get_remote_address)


async def enforce_max_body_size(request: Request) -> None:
    """Reject request bodies over MAX_BODY_BYTES. Checks Content-Length up
    front, then falls back to the actual body length in case the header is
    missing or understates the payload."""
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length.isdigit() and int(content_length) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large")
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Request body too large")

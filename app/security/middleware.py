"""Shared security dependencies for HTTP endpoints: rate limiting and a
request body size cap. Kept separate from app.security.sessions so that
transport-layer concerns don't mix with cookie signing logic."""
from fastapi import HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.security.sessions import verify_session_id

MAX_BODY_BYTES = 2048

# Report submissions carry an optional screenshot (capped at 2MB in main.py) plus
# multipart overhead for the text fields and part boundaries.
MAX_REPORT_BODY_BYTES = 2 * 1024 * 1024 + 8192


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


def _make_body_size_enforcer(max_bytes: int):
    """Build a FastAPI dependency that rejects request bodies over max_bytes.
    Checks Content-Length up front, then falls back to the actual body length
    in case the header is missing or understates the payload.

    Only safe for JSON endpoints: the `request.body()` fallback caches the raw
    bytes on `request._body`, and Starlette's multipart form parser reads the
    stream directly (bypassing that cache) — calling both on the same request
    raises "Stream consumed". Multipart routes must use
    _make_header_only_body_size_enforcer instead."""
    async def _enforce(request: Request) -> None:
        content_length = request.headers.get("content-length")
        if content_length is not None and content_length.isdigit() and int(content_length) > max_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")
        body = await request.body()
        if len(body) > max_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")
    return _enforce


def _make_header_only_body_size_enforcer(max_bytes: int):
    """Like _make_body_size_enforcer, but Content-Length only — never reads the
    body. Required for multipart/form-data routes (see docstring above); also
    rejects requests with no Content-Length at all (e.g. chunked transfer),
    since that's otherwise an unbounded-read vector when the body can't be
    pre-checked."""
    async def _enforce(request: Request) -> None:
        content_length = request.headers.get("content-length")
        if content_length is None or not content_length.isdigit():
            raise HTTPException(status_code=411, detail="Content-Length header required")
        if int(content_length) > max_bytes:
            raise HTTPException(status_code=413, detail="Request body too large")
    return _enforce


enforce_max_body_size = _make_body_size_enforcer(MAX_BODY_BYTES)
enforce_report_body_size = _make_header_only_body_size_enforcer(MAX_REPORT_BODY_BYTES)

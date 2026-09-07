import json
import logging
import re
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import uvicorn
from app import config
from app.agent import get_agent
from app.schools import get_school, load_schools
from app.security.chatbox_token import verify_chatbox_token
from app.security.middleware import (
    enforce_max_body_size,
    enforce_report_body_size,
    limiter,
    session_or_ip_key,
)
from app.security.sessions import issue_session_id, verify_session_id
from app.store.postgres_store import store as postgres_store

logger = logging.getLogger(__name__)

app = FastAPI(title="DUSD School Chatbot")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Log every unhandled exception with full traceback + request context,
    then return HTTP 500 with a generic body. Prevents the previous pattern
    of catching exceptions inside the agent and returning HTTP 200 with the
    raw error text — that hid failures from Cloud Run's error tracker and
    leaked internal details to end users. The chatbox already renders a
    friendly "Sorry, something went wrong (HTTP 500)" message on any non-2xx,
    so users still get a graceful UX."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_origin_regex=config.ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

SESSION_COOKIE_NAME = "wms_session"
SESSION_COOKIE_MAX_AGE = 24 * 60 * 60  # matches RedisStore's conversation TTL

CHATBOX_HTML = Path(__file__).parent / "chatbox.html"
EXPIRED_LINK_HTML = Path(__file__).parent / "static" / "expired-link.html"
EMBED_JS = Path(__file__).parent / "embed" / "wms-chatbot.js"
STATIC_DIR = Path(__file__).parent / "static"

# PWA icon filename patterns generated per-school by scripts/generate_icons.py
# (#52) — kept in one place so /manifest.webmanifest and any future caller
# agree on naming.
SCHOOL_ICON_VARIANTS = [
    ("icon-192-{}.png", "192x192", "any"),
    ("icon-512-{}.png", "512x512", "any"),
    ("icon-512-maskable-{}.png", "512x512", "maskable"),
]


def _public_school_theme() -> dict:
    """Per-school branding safe to expose to the chatbox frontend (#52) — name
    and colors only, none of the operational fields (phone, bell schedule,
    etc.) that SchoolConfig also carries. Embedded into chatbox.html at
    request time so the widget can render the pinned school's theme without
    an extra round trip, and can react live if the dev-only school picker is
    used to switch schools."""
    return {
        school.id: {
            "name": school.name,
            "theme_color": school.theme_color,
            "primary_bubble_color": school.primary_bubble_color,
            "background_tint": school.background_tint,
            "logo_url": school.logo_url,
        }
        for school in load_schools().values()
    }


class ChatRequest(BaseModel):
    message: str
    school_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    attach_map: bool


class ThanksRequest(BaseModel):
    school_id: str | None = None


MAX_SCREENSHOT_BYTES = 2 * 1024 * 1024
ALLOWED_SCREENSHOT_CONTENT_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@app.on_event("startup")
async def on_startup():
    # Dev-only escape hatch for previewing UI changes without a local
    # Postgres. /chat will still fail if hit, but /chatbox + PWA assets serve
    # normally. Never set in production — Cloud Run leaves it unset so the
    # startup schema check catches DB misconfiguration before the first
    # request lands.
    import os
    if os.getenv("SKIP_DB_INIT"):
        logger.warning("SKIP_DB_INIT set — skipping postgres_store.init_schema()")
        return
    postgres_store.init_schema()


@app.get("/")
async def root():
    return {"status": "ok", "message": "DUSD School Chatbot is running"}


@app.get("/chatbox")
async def chatbox(
    token: str | None = Query(default=None),
    school: str | None = Query(default=None),
):
    """Serves the standalone web chat widget from the same origin as /chat, so
    the session cookie is first-party. Opening chatbox.html via file:// breaks
    cookie storage under browsers' cross-origin Secure-cookie rules.

    Gated behind a signed, self-expiring token (app/security/chatbox_token.py).
    Missing/invalid tokens render a friendly HTML "link expired" page (with a
    404 status) instead of a raw JSON error, because installed PWAs commonly
    land here after their embedded token expires — showing them "detail not
    found" was the worst possible first impression.

    `school` (#52) pins per-school branding: it's forwarded into the manifest
    link so the installed PWA gets that school's icon, and — when a matching
    apple-touch-icon-<id>.png exists — swapped into the static apple-touch-icon
    link too, since iOS reads that tag at page-load time, before any JS runs."""
    if token is None or not verify_chatbox_token(token):
        return HTMLResponse(
            EXPIRED_LINK_HTML.read_text(),
            status_code=404,
            headers={"cache-control": "no-store"},
        )
    school_config = get_school(school) if school else None

    # Server-side interpolation of the manifest URL so the token (and pinned
    # school) are present BEFORE any JS runs. iOS Safari fetches the manifest
    # early — often before a client-side updater has a chance to rewrite the
    # href — so relying on JS to inject them race-conditions the install: the
    # manifest gets cached with the wrong start_url/icon, and the installed
    # PWA opens /chatbox with no token and 404s. Interpolating at HTML
    # delivery time avoids the race entirely.
    manifest_href = f"/manifest.webmanifest?token={token}"
    if school_config:
        manifest_href += f"&school={school_config.id}"
    html = CHATBOX_HTML.read_text().replace(
        '<link rel="manifest" href="/manifest.webmanifest">',
        f'<link rel="manifest" href="{manifest_href}">',
    )

    if school_config:
        touch_icon_filename = f"apple-touch-icon-{school_config.id}.png"
        if (STATIC_DIR / "icons" / touch_icon_filename).is_file():
            html = html.replace(
                '<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">',
                f'<link rel="apple-touch-icon" href="/icons/{touch_icon_filename}">',
            )

    # Embed public per-school theme data so the header/bubble colors can be
    # applied without an extra network round trip (and so the dev-only school
    # picker can switch themes live client-side).
    html = html.replace(
        '<script id="school-theme-data" type="application/json">{}</script>',
        f'<script id="school-theme-data" type="application/json">{json.dumps(_public_school_theme())}</script>',
    )
    return HTMLResponse(html, headers={"cache-control": "no-store"})


@app.get("/embed/wms-chatbot.js")
async def embed_script():
    """Serves the iframe-embed snippet. Interim hosting until Sprint 1.7 (#10)
    provisions Cloud Storage + Cloud CDN for static assets."""
    return FileResponse(EMBED_JS, media_type="application/javascript")


@app.get("/manifest.webmanifest")
async def pwa_manifest(
    token: str | None = Query(default=None),
    school: str | None = Query(default=None),
):
    """PWA manifest for iOS/Android "Add to Home Screen" installs.

    Dynamic so `start_url` can preserve the caller's chatbox token — otherwise
    launching the installed app from the home screen would land on /chatbox
    with no token and 404. When the token expires the icon still opens, but
    hits the 404; the user then requests a fresh link. Invalid/missing tokens
    fall back to a plain /chatbox start_url so the manifest still installs
    cleanly (useful during local dev without the token gate).

    `school` (#52) swaps in that school's branded name/colors/icons — e.g.
    /manifest.webmanifest?school=wells&token=... — so a school-scoped install
    gets that school's icon on the home screen instead of the generic DUSD
    one. Unknown school ids, or a school whose branded icon set hasn't been
    generated yet (scripts/generate_icons.py), fall back to the generic
    manifest untouched so installs never break."""
    manifest = json.loads((STATIC_DIR / "manifest.webmanifest").read_text())

    start_url = "/chatbox"
    if token and verify_chatbox_token(token):
        start_url = f"/chatbox?token={token}"
        if school:
            start_url += f"&school={school}"
    manifest["start_url"] = start_url

    school_config = get_school(school) if school else None
    if school_config:
        manifest["name"] = f"{school_config.name} Chat"
        manifest["short_name"] = f"{school_config.name.split()[0]} Chat"
        if school_config.theme_color:
            manifest["theme_color"] = school_config.theme_color
        if school_config.background_tint:
            manifest["background_color"] = school_config.background_tint

        branded_icons = []
        for pattern, sizes, purpose in SCHOOL_ICON_VARIANTS:
            filename = pattern.format(school_config.id)
            if (STATIC_DIR / "icons" / filename).is_file():
                branded_icons.append(
                    {"src": f"/icons/{filename}", "sizes": sizes, "type": "image/png", "purpose": purpose}
                )
        # Only swap in the branded set if every variant exists on disk — a
        # partial set would leave some install surfaces (e.g. Android's
        # maskable adaptive icon) with a missing icon and a broken install.
        if len(branded_icons) == len(SCHOOL_ICON_VARIANTS):
            manifest["icons"] = branded_icons

    return JSONResponse(manifest, media_type="application/manifest+json")


@app.get("/icons/{filename}")
async def pwa_icon(filename: str):
    """Static PNG icons for the PWA manifest + iOS apple-touch-icon.

    Not token-gated: the browser fetches these before/during install, from a
    context (Safari's install sheet) where cookies/tokens don't reliably ride
    along. The icons are non-sensitive branded assets, so open access is fine."""
    # Guard against path traversal — reject anything not a plain filename.
    if "/" in filename or ".." in filename or not filename.endswith(".png"):
        raise HTTPException(status_code=404)
    icon_path = STATIC_DIR / "icons" / filename
    if not icon_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(icon_path, media_type="image/png")


def _resolve_session_id(wms_session: str | None, response: Response) -> str:
    """Reuse a valid session cookie, or mint and set a fresh one. Raises 401 if
    a cookie was presented but fails signature verification. Session identity
    always comes from this server-signed cookie — the client cannot claim an
    arbitrary user_id."""
    if wms_session is None:
        session_id, cookie_value = issue_session_id()
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie_value,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=SESSION_COOKIE_MAX_AGE,
        )
        return session_id
    session_id = verify_session_id(wms_session)
    if session_id is None:
        raise HTTPException(status_code=401, detail="Invalid session cookie")
    return session_id


@app.get("/fonts/{filename}")
async def a11y_font(filename: str):
    """Serves the OpenDyslexic webfont bundled for the chatbox's accessibility
    settings panel (issue #64). Bundled locally rather than pulled from a CDN
    so the dyslexia-friendly font toggle keeps working even if a third-party
    font host is blocked or offline. Not token-gated, same reasoning as
    /icons/{filename}: non-sensitive static assets, open access is fine."""
    # Guard against path traversal — reject anything not a plain .woff2 filename.
    if "/" in filename or ".." in filename or not filename.endswith(".woff2"):
        raise HTTPException(status_code=404)
    font_path = STATIC_DIR / "fonts" / filename
    if not font_path.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(font_path, media_type="font/woff2")


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_max_body_size)])
@limiter.limit("10/minute")
@limiter.limit("30/minute", key_func=session_or_ip_key)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    response: Response,
    wms_session: str | None = Cookie(default=None),
):
    """Endpoint for the web chat widget."""
    session_id = _resolve_session_id(wms_session, response)

    school_id = chat_request.school_id or config.DEFAULT_SCHOOL_ID
    agent = get_agent(school_id)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown school: {school_id}")

    reply = agent.chat(chat_request.message, user_id=session_id)
    return ChatResponse(reply=reply.text, attach_map=reply.attach_map)


@app.post("/feedback/thanks", dependencies=[Depends(enforce_max_body_size)])
@limiter.limit("10/minute")
@limiter.limit("30/minute", key_func=session_or_ip_key)
async def thanks(
    request: Request,
    thanks_request: ThanksRequest,
    response: Response,
    wms_session: str | None = Cookie(default=None),
):
    """One-tap 'send thanks' from the help popover — lightweight positive
    feedback with no form to fill out."""
    session_id = _resolve_session_id(wms_session, response)

    school_id = thanks_request.school_id or config.DEFAULT_SCHOOL_ID
    agent = get_agent(school_id)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown school: {school_id}")

    agent.record_thanks(user_id=session_id)
    return {"status": "ok"}


@app.post("/feedback/report", dependencies=[Depends(enforce_report_body_size)])
@limiter.limit("5/minute")
@limiter.limit("15/minute", key_func=session_or_ip_key)
async def report(
    request: Request,
    response: Response,
    name: str = Form(...),
    email: str = Form(...),
    message: str = Form(...),
    school_id: str | None = Form(default=None),
    screenshot: UploadFile | None = File(default=None),
    wms_session: str | None = Cookie(default=None),
):
    """Problem-report form surfaced from the help popover: name, email, a
    description of the issue, and an optional screenshot. Replaces the old
    in-chat /report command with structured submissions reviewers can act on."""
    name = name.strip()
    email = email.strip()
    message = message.strip()
    if not name or not email or not message:
        raise HTTPException(status_code=422, detail="Name, email, and problem description are required")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")

    session_id = _resolve_session_id(wms_session, response)

    resolved_school_id = school_id or config.DEFAULT_SCHOOL_ID
    agent = get_agent(resolved_school_id)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown school: {resolved_school_id}")

    screenshot_bytes = None
    screenshot_content_type = ""
    if screenshot is not None and screenshot.filename:
        if screenshot.content_type not in ALLOWED_SCREENSHOT_CONTENT_TYPES:
            raise HTTPException(status_code=415, detail="Screenshot must be a PNG, JPEG, WEBP, or GIF image")
        screenshot_bytes = await screenshot.read()
        if len(screenshot_bytes) > MAX_SCREENSHOT_BYTES:
            raise HTTPException(status_code=413, detail="Screenshot must be under 2MB")
        screenshot_content_type = screenshot.content_type

    agent.record_report(
        user_id=session_id,
        name=name,
        email=email,
        message=message,
        screenshot=screenshot_bytes,
        screenshot_content_type=screenshot_content_type,
    )
    return {"status": "ok"}


if __name__ == "__main__":
    print(f"Starting DUSD School Chatbot on port {config.PORT}")
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

import json
import logging
import os
import re
import uuid
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
from app.daily_cap import FRIENDLY_CAP_MESSAGE, check_and_increment
from app.schools import get_school, load_schools
from app.security.chatbox_token import (
    TOKEN_EXPIRED,
    TOKEN_MALFORMED,
    TOKEN_MISSING,
    classify_chatbox_token,
    verify_chatbox_token,
)
from app.security.identity import resolve_user_id
from app.security.middleware import (
    enforce_max_body_size,
    enforce_report_body_size,
    limiter,
    session_or_ip_key,
)
from app.store.postgres_store import store as postgres_store
from app.store.redis_store import store as redis_store

# Without this, the root logger defaults to WARNING and every INFO-level log
# (e.g. app.agent's per-message Anthropic usage/cost logging) is silently
# dropped rather than reaching stdout — which is what Cloud Run ships to
# Google Cloud Logging. This must run at import time, since Cloud Run's
# entrypoint is `uvicorn main:app`, not the `__main__` block below.
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="DUSD School Chatbot")

# Lets an already-open tab/installed PWA detect that a newer version has
# been deployed and prompt the user to refresh, instead of silently running
# stale code until they close and reopen the app themselves. K_REVISION is
# set automatically by Cloud Run to the current revision name, so a real
# deploy changes it with zero extra plumbing; local/other environments fall
# back to a random value picked once at process start, which still works
# for testing (restarting the dev server "deploys" a new version) even
# though it isn't a meaningful version string outside Cloud Run.
APP_VERSION = os.environ.get("K_REVISION") or str(uuid.uuid4())

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
    # Without this, a browser's fetch() can't read X-App-Version off a
    # cross-origin response (the CORS default only exposes a small header
    # safelist) — matters if /chat is ever called cross-origin rather than
    # from the same-origin /chatbox iframe embed/wms-chatbot.js sets up.
    expose_headers=["X-App-Version"],
)


@app.middleware("http")
async def _add_app_version_header(request: Request, call_next):
    """Stamps every response with the running version, so the chatbox can
    detect a new deploy from a response it already gets back during normal
    use (see checkAppVersion() in chatbox.html) instead of polling a
    separate endpoint."""
    response = await call_next(request)
    response.headers["X-App-Version"] = APP_VERSION
    return response


CHATBOX_HTML = Path(__file__).parent / "chatbox.html"
LINK_UNAVAILABLE_HTML = Path(__file__).parent / "static" / "link-unavailable.html"
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
    """Per-school branding safe to expose to the chatbox frontend (#52) — name,
    colors, and the bell schedule link. Everything here is either cosmetic or
    a public URL (same sensitivity as school.website, unlike phone/address),
    so none of it needs to go through the AI. Embedded into chatbox.html at
    request time so the widget can render the pinned school's theme (and its
    always-visible bell schedule link) without an extra round trip, and can
    react live if the dev-only school picker is used to switch schools."""
    return {
        school.id: {
            "name": school.name,
            "level": school.level,
            "theme_color": school.theme_color,
            "primary_bubble_color": school.primary_bubble_color,
            "background_tint": school.background_tint,
            "logo_url": school.logo_url,
            "bell_schedule_url": school.bell_schedule_url or school.website,
        }
        for school in load_schools().values()
    }


ANNOUNCEMENTS_FILE = Path(__file__).parent / "data" / "announcements.json"

# However long data/announcements.json grows over time, a returning user
# should see a short "what's changed recently" list, not the app's entire
# feature history — the popover isn't meant to be a scrollable archive.
MAX_ANNOUNCEMENTS_SHOWN = 10


def _public_announcements() -> dict:
    """Per-school feature-announcement feed for the chatbox's "what's new"
    button — a small, app-wide changelog (data/announcements.json), each
    entry tagged with which school(s) it applies to. Newest-first order is
    the source file's job, not this function's (so the file itself is the
    readable changelog) — this only caps how many of those entries are sent.
    Embedded into chatbox.html the same way as _public_school_theme() — no
    extra round trip, and live-reactive if the dev-only school picker
    switches schools.

    A missing/unreadable file degrades to "no announcements for anyone"
    rather than breaking /chatbox — this is a nice-to-have nudge, not
    something that should ever block the chat widget from loading."""
    try:
        all_announcements = json.loads(ANNOUNCEMENTS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        all_announcements = []

    return {
        school.id: [
            {"id": a["id"], "date": a["date"], "title": a["title"], "text": a["text"]}
            for a in all_announcements
            if not a.get("schools") or school.id in a["schools"]
        ][:MAX_ANNOUNCEMENTS_SHOWN]
        for school in load_schools().values()
    }


class ChatRequest(BaseModel):
    message: str
    school_id: str | None = None
    # Chatbox language toggle (#62) — EN/ES/中文. Optional so older embeds/
    # clients that don't send it keep working: SchoolAgent.chat() falls back
    # to whatever was last persisted for the session, or English if nothing
    # was ever set.
    language: str | None = None


class ChatResponse(BaseModel):
    reply: str
    attach_map: bool


class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    messages: list[HistoryMessage]


class ThanksRequest(BaseModel):
    school_id: str | None = None



# One <main> block per reason a chatbox link can be rejected. The EXPIRED
# entry must stay byte-identical to the default already in
# link-unavailable.html — that's what _link_unavailable_page swaps out — so
# the file remains a correct standalone page and the swap has something to
# match. tests/test_main.py asserts each reason renders its own distinctive
# copy, which is what catches drift between the two.
#
# Worth keeping distinct because "expired" was previously shown for ALL
# THREE cases, and a damaged link is the one people actually hit: tokens
# get truncated by chat clients, mangled by markdown escaping (a generic
# token's user_id field is a literal "*", which renders as "\*"), or
# copied without their last line. Telling someone their perfectly good
# link "expired" sends them to ask for a replacement that will fail the
# exact same way.
LINK_PROBLEM_BLOCKS = {
    TOKEN_EXPIRED: """<main>
  <div class="icon" aria-hidden="true">⏱</div>
  <h1>Your access link has expired</h1>
  <p>
    This preview link is only valid for a limited time.
    Ask Karanveer for a fresh link and try again.
  </p>
  <p class="hint">
    If you installed this app from an expired link, delete the icon and add
    it again from the new link.
  </p>
</main>""",
    TOKEN_MALFORMED: """<main>
  <div class="icon" aria-hidden="true">✂</div>
  <h1>This link looks incomplete</h1>
  <p>
    Your link may not have copied across in full — chat apps and email
    sometimes cut the end off, or break it across two lines.
  </p>
  <p class="hint">
    Go back to where you got it, copy the whole link in one piece, and paste
    it into your browser's address bar. If it still doesn't open, ask
    Karanveer for a new one.
  </p>
</main>""",
    TOKEN_MISSING: """<main>
  <div class="icon" aria-hidden="true">🔗</div>
  <h1>You need an access link</h1>
  <p>
    This chat is opened through a personal link rather than from this page.
  </p>
  <p class="hint">
    If you installed this app from a link that has since expired, delete the
    icon and add it again from a fresh link. Otherwise, ask Karanveer for
    one.
  </p>
</main>""",
}


def _link_unavailable_page(reason: str) -> str:
    """The link-unavailable page, worded for why the link was rejected.
    Falls back to the file's default (expired) wording for an unrecognised
    reason, so a new reason added to chatbox_token.py renders something
    sane instead of raising on a user-facing error path."""
    page = LINK_UNAVAILABLE_HTML.read_text()
    block = LINK_PROBLEM_BLOCKS.get(reason)
    if block is None or reason == TOKEN_EXPIRED:
        return page
    return page.replace(LINK_PROBLEM_BLOCKS[TOKEN_EXPIRED], block)


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
    Rejected tokens render a friendly HTML page (with a 404 status) instead
    of a raw JSON error, because installed PWAs commonly land here after
    their embedded token expires — showing them "detail not found" was the
    worst possible first impression. The page is worded for WHY the token
    was rejected (see LINK_PROBLEM_BLOCKS): a link that lapsed and a link
    that arrived truncated need opposite instructions, and saying "expired"
    for both sends people to request a replacement that fails identically.

    `school` (#52) pins per-school branding: it's forwarded into the manifest
    link so the installed PWA gets that school's icon, and — when a matching
    apple-touch-icon-<id>.png exists — swapped into the static apple-touch-icon
    link too, since iOS reads that tag at page-load time, before any JS runs."""
    rejection = classify_chatbox_token(token)
    if rejection is not None:
        return HTMLResponse(
            _link_unavailable_page(rejection),
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
    # Same embed-at-render-time pattern as school-theme-data above, for the
    # chatbox's "what's new" button (#feature-announcements).
    html = html.replace(
        '<script id="announcements-data" type="application/json">{}</script>',
        f'<script id="announcements-data" type="application/json">{json.dumps(_public_announcements())}</script>',
    )
    # Same pattern again, for the "update available" banner — the version
    # active when this page was rendered, so the client can tell it apart
    # from the X-App-Version header on a later /chat response.
    html = html.replace(
        '<script id="app-version-data" type="application/json">{}</script>',
        f'<script id="app-version-data" type="application/json">{json.dumps({"version": APP_VERSION})}</script>',
    )
    return HTMLResponse(html, headers={"cache-control": "no-store"})


@app.get("/version")
async def version():
    """Manual/ops visibility into which revision is actually live (e.g.
    `curl .../version` after a deploy). The chatbox itself doesn't poll this
    — see the X-App-Version response header (added by a middleware above)
    for how it detects a new deploy during normal use instead."""
    return {"version": APP_VERSION}


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


# ── Root-level browser-probe paths ──────────────────────────────────────────
# Browsers auto-request /favicon.ico on every page load, and iOS Safari probes
# a handful of well-known apple-touch-icon-* paths (with/without -precomposed,
# with/without a size suffix) before it parses the HTML's <link> tags — so
# even though the chatbox HTML DOES declare /icons/apple-touch-icon.png, iOS
# still asks for the root-level paths. Without these aliases the Cloud Run
# 4xx graph fills with harmless 404s that drown out real errors.
_ROOT_FAVICON_PATH = STATIC_DIR / "icons" / "icon-192.png"
_ROOT_APPLE_TOUCH_ICON_PATH = STATIC_DIR / "icons" / "apple-touch-icon.png"
# Cache aggressively — the underlying PNGs only change when the icon design
# changes, and the file path (not content) is what browsers key their cache on.
_ROOT_ICON_CACHE_HEADERS = {"cache-control": "public, max-age=86400"}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # image/png (not image/x-icon) is what the file actually is — every current
    # browser accepts a PNG served at /favicon.ico.
    return FileResponse(_ROOT_FAVICON_PATH, media_type="image/png", headers=_ROOT_ICON_CACHE_HEADERS)


async def _root_apple_touch_icon():
    return FileResponse(
        _ROOT_APPLE_TOUCH_ICON_PATH, media_type="image/png", headers=_ROOT_ICON_CACHE_HEADERS
    )


# Aliases iOS Safari probes at the root before reading the HTML's <link
# rel="apple-touch-icon">. All resolve to the same 180x180 PNG — iOS scales
# it down for the smaller variants.
for _apple_touch_icon_alias in (
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
    "/apple-touch-icon-120x120.png",
    "/apple-touch-icon-120x120-precomposed.png",
):
    app.add_api_route(
        _apple_touch_icon_alias,
        _root_apple_touch_icon,
        methods=["GET"],
        include_in_schema=False,
    )


@app.get("/schools/{school_id}/campus-map")
async def campus_map_image(school_id: str):
    """Serves a school's campus map image from our own origin. The repo is
    private, so a raw.githubusercontent.com link 404s for any unauthenticated
    visitor — this is what campus_map.json's map_url should point to instead.
    Not gated: same reasoning as /icons — non-sensitive, publicly-relevant info."""
    school = get_school(school_id)
    if school is None or school.campus_map_file is None:
        raise HTTPException(status_code=404)
    image_candidates = sorted(
        p for p in school.campus_map_file.parent.glob("campus_map.*")
        if p.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not image_candidates:
        raise HTTPException(status_code=404)
    image_path = image_candidates[0]
    media_type = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(image_path, media_type=media_type, headers={"cache-control": "public, max-age=86400"})


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
    token: str | None = Query(default=None),
):
    """Endpoint for the web chat widget.

    `token` (#51) is the same chatbox link token used to gate /chatbox — when
    the frontend forwards it here (see chatbox.html), it resolves to a
    stable user_id shared across Safari and an installed PWA's separate
    cookie jar. See app/security/identity.py for the resolution order."""
    user_id = resolve_user_id(token, wms_session, response)

    school_id = chat_request.school_id or config.DEFAULT_SCHOOL_ID
    school = get_school(school_id)
    agent = get_agent(school_id)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown school: {school_id}")

    # Cost/abuse guard (#71): per-user daily message cap, checked before the
    # request reaches the (billed) Claude API call in agent.chat.
    cap_result = check_and_increment(user_id, school, redis_store=redis_store)
    if not cap_result.allowed:
        raise HTTPException(
            status_code=429,
            detail=FRIENDLY_CAP_MESSAGE,
            headers={"Retry-After": str(cap_result.retry_after_seconds)},
        )

    reply = agent.chat(chat_request.message, user_id=user_id, language=chat_request.language)
    text = reply.text
    if cap_result.approaching_limit:
        plural = "s" if cap_result.remaining != 1 else ""
        text += f"\n\n_You have {cap_result.remaining} message{plural} left today._"
    return ChatResponse(reply=text, attach_map=reply.attach_map)


def _flatten_history_for_display(stored: list) -> list[HistoryMessage]:
    """Collapse Redis-stored history to the string shape the chatbox renders.

    A tool-use round trip is persisted as an assistant turn whose content is
    a list of text/tool_use blocks, followed by a user turn whose content is
    a list of tool_result blocks (see _persistable_assistant_content /
    _persistable_tool_results in app/agent.py). Neither fits HistoryMessage's
    str content, and neither is user-visible: the chatbox originally showed
    only the final text reply. So we join the assistant text blocks into one
    string and drop the tool_result turns entirely."""
    out: list[HistoryMessage] = []
    for msg in stored:
        role = msg.get("role")
        content = msg.get("content")
        if isinstance(content, str):
            out.append(HistoryMessage(role=role, content=content))
            continue
        if role == "assistant" and isinstance(content, list):
            text = "".join(
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            )
            if text:
                out.append(HistoryMessage(role=role, content=text))
    return out


@app.get("/chat/history", response_model=HistoryResponse)
@limiter.limit("30/minute", key_func=session_or_ip_key)
async def chat_history(
    request: Request,
    response: Response,
    school_id: str | None = Query(default=None),
    limit: int = Query(default=50, gt=0),
    wms_session: str | None = Cookie(default=None),
    token: str | None = Query(default=None),
):
    """Restore chat history on chatbox reopen (#73) — same session identity
    resolution as /chat, so this reflects whatever conversation state that
    identity has actually accumulated. Read-only and free (no Claude API
    call), so only the per-session/IP burst limit applies, not the
    stricter global one /chat uses to bound cost."""
    user_id = resolve_user_id(token, wms_session, response)

    resolved_school_id = school_id or config.DEFAULT_SCHOOL_ID
    agent = get_agent(resolved_school_id)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown school: {resolved_school_id}")

    messages = agent.get_history(user_id, limit=limit)
    return HistoryResponse(messages=_flatten_history_for_display(messages))


@app.post("/feedback/thanks", dependencies=[Depends(enforce_max_body_size)])
@limiter.limit("10/minute")
@limiter.limit("30/minute", key_func=session_or_ip_key)
async def thanks(
    request: Request,
    thanks_request: ThanksRequest,
    response: Response,
    wms_session: str | None = Cookie(default=None),
    token: str | None = Query(default=None),
):
    """One-tap 'send thanks' from the help popover — lightweight positive
    feedback with no form to fill out."""
    user_id = resolve_user_id(token, wms_session, response)

    school_id = thanks_request.school_id or config.DEFAULT_SCHOOL_ID
    agent = get_agent(school_id)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown school: {school_id}")

    agent.record_thanks(user_id=user_id)
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
    report_type: str = Form(default="problem"),
    school_id: str | None = Form(default=None),
    screenshot: UploadFile | None = File(default=None),
    wms_session: str | None = Cookie(default=None),
    token: str | None = Query(default=None),
):
    """Report form surfaced from the help popover: name, email, a
    description, an optional screenshot, and whether it's a problem or a
    feature idea (report_type). Replaces the old in-chat /report command
    with structured submissions reviewers can act on."""
    name = name.strip()
    email = email.strip()
    message = message.strip()
    if not name or not email or not message:
        raise HTTPException(status_code=422, detail="Name, email, and description are required")
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if report_type not in ("problem", "feature"):
        raise HTTPException(status_code=422, detail="report_type must be 'problem' or 'feature'")

    user_id = resolve_user_id(token, wms_session, response)

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
        user_id=user_id,
        name=name,
        email=email,
        message=message,
        report_type=report_type,
        screenshot=screenshot_bytes,
        screenshot_content_type=screenshot_content_type,
    )
    return {"status": "ok"}


if __name__ == "__main__":
    print(f"Starting DUSD School Chatbot on port {config.PORT}")
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

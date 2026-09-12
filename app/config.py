import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Server Configuration
PORT = int(os.getenv("PORT", 8000))

# Redis Configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Postgres Configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://wms:wms@localhost:5432/wms")

# Session Cookie Signing (web chat widget)
SESSION_SIGNING_KEY = os.getenv("SESSION_SIGNING_KEY")

# Chatbox link-gate token signing — separate key from SESSION_SIGNING_KEY so
# rotating one doesn't invalidate the other.
CHATBOX_TOKEN_SIGNING_KEY = os.getenv("CHATBOX_TOKEN_SIGNING_KEY")

# CORS: every DUSD school site is a *.dublinusd.org subdomain (or the apex
# domain itself), so a single regex covers the whole district — onboarding a
# new school (app/schools.py) needs no CORS change. Anchored at both ends so
# it can't be satisfied by a suffix match like https://dublinusd.org.evil.com.
ALLOWED_ORIGIN_REGEX = r"^https://([a-zA-Z0-9-]+\.)*dublinusd\.org$"

# Extra exact origins allowed on top of the regex above — e.g. a staging
# domain that isn't under dublinusd.org.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# School resolved for a /chat request that doesn't specify school_id — keeps
# embeds that predate multi-school support working unmodified.
DEFAULT_SCHOOL_ID = os.getenv("DEFAULT_SCHOOL_ID", "wells")

# Public origin this app is reachable at (e.g. https://chat.dublinusd.org or a
# Cloud Run *.run.app URL). Used to build absolute links — e.g. the campus map
# image at /schools/{id}/campus-map — that get echoed into chat replies, since
# a relative path won't reliably render as a clickable link there. Unset in
# local dev; set this once the app has a stable deployed URL.
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# Daily message cap (#71): a cost/abuse guard on /chat. Default per-user cap
# when a school doesn't override it via daily_message_cap in its school.json
# (app/schools.py). 20/day is a starting point, pending real usage telemetry.
DEFAULT_DAILY_MESSAGE_CAP = int(os.getenv("DEFAULT_DAILY_MESSAGE_CAP", "20"))

# Session ids exempt from the daily message cap — staff/testing accounts
# (#71). A session id is only known after a user's first /chat request (it's
# embedded in their signed wms_session cookie, app/security/sessions.py), so
# whitelisting is a manual, after-the-fact step: pull the id for a known
# staff browser (e.g. from server logs) and add it here.
DAILY_CAP_WHITELIST = {
    session_id.strip()
    for session_id in os.getenv("DAILY_CAP_WHITELIST", "").split(",")
    if session_id.strip()
}

# Prompt-cache TTL for the tools+system-prompt breakpoint (app/agent.py), which
# is shared across every user of a school. Anthropic's default ephemeral cache
# is 5 minutes; a 1-hour cache write costs 2x instead of 1.25x, so it only pays
# for itself once a school sees 3+ requests within that hour. This app is new
# with no real traffic data yet — default to "5m" (Anthropic's own default,
# passed explicitly here so the two are never silently different) until usage
# in the Anthropic Console shows whether requests per school cluster within an
# hour; flip to "1h" via env var then, no code change needed.
PROMPT_CACHE_TTL = os.getenv("PROMPT_CACHE_TTL", "5m")
if PROMPT_CACHE_TTL not in ("5m", "1h"):
    raise ValueError(f"PROMPT_CACHE_TTL must be '5m' or '1h', got {PROMPT_CACHE_TTL!r}")

# WebsiteScraper's (app/services/scraper.py) in-memory per-page cache TTL.
# Cloud Run keeps at least one instance warm (infra/envs/staging/main.tf), so
# without a TTL a scraped page could stay stale for as long as that instance
# lives — potentially days — with no way to see a school's own site updates
# (staff directory, academics page, ...) short of a redeploy. 1 hour balances
# freshness against not re-scraping the same page on every single request.
SCRAPER_CACHE_TTL_SECONDS = int(os.getenv("SCRAPER_CACHE_TTL_SECONDS", "3600"))

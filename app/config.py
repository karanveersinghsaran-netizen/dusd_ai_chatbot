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

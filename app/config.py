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

# CORS: extra origins allowed to call the web /chat endpoint from browser JS,
# on top of every registered school's own allowed_origin (see app/schools.py).
# Useful for a staging origin that isn't tied to a real school yet.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
]

# School resolved for a /chat request that doesn't specify school_id — keeps
# embeds that predate multi-school support working unmodified.
DEFAULT_SCHOOL_ID = os.getenv("DEFAULT_SCHOOL_ID", "wells")

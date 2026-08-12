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

# CORS: origins allowed to call the web /chat endpoint from browser JS.
# Comma-separated env override lets a staging origin be added without a code change.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "https://wms.dublinusd.org").split(",")
    if origin.strip()
]

# School Website
SCHOOL_WEBSITE = "https://wms.dublinusd.org/"

# School Info
SCHOOL_NAME = "Wells Middle School"
SCHOOL_DISTRICT = "Dublin Unified School District"

import os
from dotenv import load_dotenv

load_dotenv()

# Anthropic Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Twilio Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

# Server Configuration
PORT = int(os.getenv("PORT", 8000))

# School Website
SCHOOL_WEBSITE = "https://wms.dublinusd.org/"

# School Info
SCHOOL_NAME = "Wells Middle School"
SCHOOL_DISTRICT = "Dublin Unified School District"

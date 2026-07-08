# Wells Middle School AI Chatbot

[![tests](https://github.com/karanveersinghsaran-netizen/wms_ai_chatbot/actions/workflows/tests.yml/badge.svg)](https://github.com/karanveersinghsaran-netizen/wms_ai_chatbot/actions/workflows/tests.yml)

A WhatsApp chatbot for Wells Middle School (Dublin Unified School District) powered by Claude AI. It answers questions about the school by scraping the school website in real time.

## Features

- WhatsApp integration via Twilio
- AI-powered responses using Claude (Anthropic)
- Live school website scraping for up-to-date information
- Per-user conversation history

## Tech Stack

- **FastAPI** — REST API and webhook handler
- **Twilio** — WhatsApp messaging
- **Anthropic Claude** — AI agent
- **BeautifulSoup** — Website scraping
- **Redis** — per-session conversation history and feedback-flow state
- **Postgres** — feedback storage

## Getting Started

### Prerequisites

- Python 3.10+
- Redis and Postgres (or Docker, to run them via `docker compose`)
- Twilio account with WhatsApp sandbox
- Anthropic API key

### Installation

```bash
git clone https://github.com/karanveersinghsaran-netizen/wms_ai_chatbot.git
cd wms_ai_chatbot
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env and fill in your API keys, plus REDIS_URL / DATABASE_URL if not using the defaults
# SESSION_SIGNING_KEY is required for the web /chat endpoint (not needed for WhatsApp only)
```

### Running

Start Redis and Postgres with Docker Compose, or point `REDIS_URL`/`DATABASE_URL` at existing instances:

```bash
docker compose up redis postgres
```

Then run the app:

```bash
python main.py
```

Or run the whole stack (app + Redis + Postgres) together, optionally with multiple app replicas:

```bash
docker compose up --build --scale app=3
```

Expose to the internet with ngrok:

```bash
ngrok http 8000
```

Then set your Twilio WhatsApp sandbox webhook to:
```
https://<your-ngrok-url>/webhook/whatsapp
```

## Project Structure

```
wms_ai_chatbot/
├── main.py              # FastAPI app and Twilio webhook
├── agent.py             # Claude AI agent with tools
├── website_scraper.py   # School website scraper
├── config.py            # Configuration and env vars
├── requirements.txt
└── .env.example
```

## License

MIT

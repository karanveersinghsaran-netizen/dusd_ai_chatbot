# Wells Middle School AI Chatbot

[![tests](https://github.com/karanveersinghsaran-netizen/wms_ai_chatbot/actions/workflows/tests.yml/badge.svg)](https://github.com/karanveersinghsaran-netizen/wms_ai_chatbot/actions/workflows/tests.yml)

A web chatbot for Wells Middle School (Dublin Unified School District) powered by Claude AI. It answers questions about the school by scraping the school website in real time.

## Features

- AI-powered responses using Claude (Anthropic)
- Live school website scraping for up-to-date information
- Per-session conversation history
- Embeddable web widget (iframe snippet) for the school website

## Tech Stack

- **FastAPI** — REST API and web chat endpoint
- **Anthropic Claude** — AI agent
- **BeautifulSoup** — Website scraping
- **Redis** — per-session conversation history and feedback-flow state
- **Postgres** — feedback storage

## Getting Started

### Prerequisites

- Python 3.10+
- Redis and Postgres (or Docker, to run them via `docker compose`)
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
# SESSION_SIGNING_KEY is required for the /chat endpoint
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

Open the chat widget at `http://localhost:8000/chatbox`, or embed it on another page — see `docs/embed.md`.

## Project Structure

```
wms_ai_chatbot/
├── main.py                    # FastAPI app: /chat, /chatbox, /embed
├── chatbox.html                # Web chat widget UI
├── embed/wms-chatbot.js        # Iframe-embed snippet for school sites
├── app/
│   ├── agent.py                 # Claude AI agent with tools
│   ├── config.py                # Configuration and env vars
│   ├── security/                # Session cookie signing, rate limiting
│   ├── services/                # Website scraper, calendar
│   └── store/                   # Redis (sessions) and Postgres (feedback)
├── data/                       # Campus map, instructional calendars
├── db/schema.sql               # Postgres schema
├── infra/                      # Terraform (GCP: Cloud Run, Cloud SQL, Redis)
├── requirements.txt
└── .env.example
```

## License

MIT

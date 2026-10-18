# DUSD AI Chatbot

[![tests](https://github.com/karanveersinghsaran-netizen/dusd_ai_chatbot/actions/workflows/tests.yml/badge.svg)](https://github.com/karanveersinghsaran-netizen/dusd_ai_chatbot/actions/workflows/tests.yml)

A web chatbot for Dublin Unified School District (DUSD) schools, powered by Claude AI. It currently serves Dublin High, Emerald High, Fallon Middle, and Wells Middle — answering parent and student questions by grounding every answer in each school's own website and official district documents (lunch menus, bell schedules, academic calendars, campus maps, and course catalogs where published).

## Features

- Multi-school: one deployment serves all four schools, each with its own theme, menus, and content — adding a new school is a `data/schools/<id>/` directory, no code change required
- AI-powered responses using Claude (Anthropic)
- Live school-website scraping for day-of information (announcements, bell schedules, calendar changes)
- Per-session conversation history over a signed-token access link
- Embeddable web widget (iframe snippet) each school can drop into its own site

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
git clone https://github.com/karanveersinghsaran-netizen/dusd_ai_chatbot.git
cd dusd_ai_chatbot
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env and fill in your API keys, plus REDIS_URL / DATABASE_URL if not using the defaults
# SESSION_SIGNING_KEY is required for the /chat endpoint
# CHATBOX_TOKEN_SIGNING_KEY is required for the /chatbox endpoint (see docs/security.md)
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

`GET /chatbox` requires a `token` query param (see `docs/security.md`); mint one with `python -m scripts.generate_chatbox_token --base-url http://localhost:8000`, then open the printed URL, or embed the widget on another page — see `docs/embed.md`.

## Project Structure

```
dusd_ai_chatbot/
├── main.py                    # FastAPI app: /chat, /chatbox, /embed
├── chatbox.html                # Web chat widget UI
├── embed/wms-chatbot.js        # Iframe-embed snippet each school drops into its own site
├── app/
│   ├── agent.py                 # Claude AI agent with tools
│   ├── config.py                # Configuration and env vars
│   ├── security/                # Session cookie signing, rate limiting
│   ├── services/                # Website scraper, calendar
│   └── store/                   # Redis (sessions) and Postgres (feedback)
├── data/                       # Campus map, instructional calendars
├── db/schema.sql               # Postgres schema
├── scripts/                    # Operator CLIs (e.g. mint a /chatbox access token)
├── requirements.txt
└── .env.example
```

## License

MIT

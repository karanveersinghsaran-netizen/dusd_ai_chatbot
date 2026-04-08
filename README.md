# Wells Middle School AI Chatbot

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

## Getting Started

### Prerequisites

- Python 3.10+
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
# Edit .env and fill in your API keys
```

### Running

```bash
python main.py
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

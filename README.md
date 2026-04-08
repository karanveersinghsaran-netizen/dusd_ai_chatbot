# WMS AI Chatbot

An AI-powered chatbot for Warehouse Management System (WMS) operations. This assistant helps warehouse staff query inventory, track shipments, manage orders, and get instant answers about warehouse operations.

## Features

- Natural language queries for inventory and order data
- Integration with WMS database
- Conversational AI powered by Claude API
- REST API backend

## Getting Started

### Prerequisites

- Python 3.10+
- pip

### Installation

```bash
git clone https://github.com/karanveersinghsaran-netizen/wms_ai_chatbot.git
cd wms_ai_chatbot
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

### Running

```bash
python main.py
```

## Project Structure

```
wms_ai_chatbot/
├── main.py           # Application entry point
├── requirements.txt  # Python dependencies
├── .env.example      # Environment variable template
└── README.md
```

## License

MIT

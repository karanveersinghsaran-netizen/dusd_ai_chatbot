from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Form, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from twilio.twiml.messaging_response import MessagingResponse
import uvicorn
from app import config
from app.agent import agent
from app.security.middleware import enforce_max_body_size, limiter, session_or_ip_key
from app.security.sessions import issue_session_id, verify_session_id
from app.store.postgres_store import store as postgres_store

app = FastAPI(title="Wells Middle School WhatsApp Bot")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["POST"],
    allow_headers=["Content-Type"],
)

SESSION_COOKIE_NAME = "wms_session"
SESSION_COOKIE_MAX_AGE = 24 * 60 * 60  # matches RedisStore's conversation TTL

CHATBOX_HTML = Path(__file__).parent / "chatbox.html"
EMBED_JS = Path(__file__).parent / "embed" / "wms-chatbot.js"


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str
    attach_map: bool


@app.on_event("startup")
async def on_startup():
    postgres_store.init_schema()


@app.get("/")
async def root():
    return {"status": "ok", "message": "Wells Middle School WhatsApp Bot is running"}


@app.get("/chatbox")
async def chatbox():
    """Serves the standalone web chat widget from the same origin as /chat, so
    the session cookie is first-party. Opening chatbox.html via file:// breaks
    cookie storage under browsers' cross-origin Secure-cookie rules."""
    return FileResponse(CHATBOX_HTML, media_type="text/html")


@app.get("/embed/wms-chatbot.js")
async def embed_script():
    """Serves the iframe-embed snippet. Interim hosting until Sprint 1.7 (#10)
    provisions Cloud Storage + Cloud CDN for static assets."""
    return FileResponse(EMBED_JS, media_type="application/javascript")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(None),
    MessageSid: str = Form(None)
):
    """Webhook endpoint for Twilio WhatsApp messages."""
    print(f"Received message from {From}: {Body}")
    reply = agent.chat(Body, user_id=From, channel="whatsapp")
    twiml_response = MessagingResponse()
    msg = twiml_response.message(reply.text)
    if reply.attach_map:
        msg.media(config.CAMPUS_MAP_URL)
    return PlainTextResponse(content=str(twiml_response), media_type="application/xml")


@app.get("/webhook/whatsapp")
async def whatsapp_webhook_get():
    return {"message": "WhatsApp webhook is active. Send POST requests here."}


@app.post("/chat", response_model=ChatResponse, dependencies=[Depends(enforce_max_body_size)])
@limiter.limit("10/minute")
@limiter.limit("30/minute", key_func=session_or_ip_key)
async def chat(
    request: Request,
    chat_request: ChatRequest,
    response: Response,
    wms_session: str | None = Cookie(default=None),
):
    """Endpoint for the web chat widget. Session identity comes only from a
    server-signed cookie — the client cannot claim an arbitrary user_id."""
    if wms_session is None:
        session_id, cookie_value = issue_session_id()
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie_value,
            httponly=True,
            secure=True,
            samesite="lax",
            max_age=SESSION_COOKIE_MAX_AGE,
        )
    else:
        session_id = verify_session_id(wms_session)
        if session_id is None:
            raise HTTPException(status_code=401, detail="Invalid session cookie")

    reply = agent.chat(chat_request.message, user_id=session_id, channel="web")
    return ChatResponse(reply=reply.text, attach_map=reply.attach_map)


if __name__ == "__main__":
    print(f"Starting Wells Middle School WhatsApp Bot on port {config.PORT}")
    print(f"Webhook URL: http://localhost:{config.PORT}/webhook/whatsapp")
    print("Use ngrok to expose this to the internet for Twilio.")
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

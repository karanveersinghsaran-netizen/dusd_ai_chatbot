from fastapi import Cookie, FastAPI, Form, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from twilio.twiml.messaging_response import MessagingResponse
import uvicorn
from app import config
from app.agent import agent
from app.security.sessions import issue_session_id, verify_session_id
from app.store.postgres_store import store as postgres_store

app = FastAPI(title="Wells Middle School WhatsApp Bot")

SESSION_COOKIE_NAME = "wms_session"
SESSION_COOKIE_MAX_AGE = 24 * 60 * 60  # matches RedisStore's conversation TTL


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


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    Body: str = Form(...),
    From: str = Form(...),
    To: str = Form(None),
    MessageSid: str = Form(None)
):
    """Webhook endpoint for Twilio WhatsApp messages."""
    print(f"Received message from {From}: {Body}")
    reply = agent.chat(Body, user_id=From)
    twiml_response = MessagingResponse()
    msg = twiml_response.message(reply.text)
    if reply.attach_map:
        msg.media(config.CAMPUS_MAP_URL)
    return PlainTextResponse(content=str(twiml_response), media_type="application/xml")


@app.get("/webhook/whatsapp")
async def whatsapp_webhook_get():
    return {"message": "WhatsApp webhook is active. Send POST requests here."}


@app.post("/chat", response_model=ChatResponse)
async def chat(
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

    reply = agent.chat(chat_request.message, user_id=session_id)
    return ChatResponse(reply=reply.text, attach_map=reply.attach_map)


if __name__ == "__main__":
    print(f"Starting Wells Middle School WhatsApp Bot on port {config.PORT}")
    print(f"Webhook URL: http://localhost:{config.PORT}/webhook/whatsapp")
    print("Use ngrok to expose this to the internet for Twilio.")
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

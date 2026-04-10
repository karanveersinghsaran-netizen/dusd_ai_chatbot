from fastapi import FastAPI, Form
from fastapi.responses import PlainTextResponse
from twilio.twiml.messaging_response import MessagingResponse
import uvicorn
from app import config
from app.agent import agent

app = FastAPI(title="Wells Middle School WhatsApp Bot")


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
    response_text = agent.chat(Body, user_id=From)
    twiml_response = MessagingResponse()
    twiml_response.message(response_text)
    return PlainTextResponse(content=str(twiml_response), media_type="application/xml")


@app.get("/webhook/whatsapp")
async def whatsapp_webhook_get():
    return {"message": "WhatsApp webhook is active. Send POST requests here."}


if __name__ == "__main__":
    print(f"Starting Wells Middle School WhatsApp Bot on port {config.PORT}")
    print(f"Webhook URL: http://localhost:{config.PORT}/webhook/whatsapp")
    print("Use ngrok to expose this to the internet for Twilio.")
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

import logging
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
import uvicorn
from app import config
from app.agent import get_agent
from app.schools import load_schools
from app.security.middleware import enforce_max_body_size, limiter, session_or_ip_key
from app.security.sessions import issue_session_id, verify_session_id
from app.store.postgres_store import store as postgres_store

logger = logging.getLogger(__name__)

app = FastAPI(title="DUSD School Chatbot")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    """Log every unhandled exception with full traceback + request context,
    then return HTTP 500 with a generic body. Prevents the previous pattern
    of catching exceptions inside the agent and returning HTTP 200 with the
    raw error text — that hid failures from Cloud Run's error tracker and
    leaked internal details to end users. The chatbox already renders a
    friendly "Sorry, something went wrong (HTTP 500)" message on any non-2xx,
    so users still get a graceful UX."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Please try again."},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(
        set(config.ALLOWED_ORIGINS) | {s.allowed_origin for s in load_schools().values()}
    ),
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
    school_id: str | None = None


class ChatResponse(BaseModel):
    reply: str
    attach_map: bool


@app.on_event("startup")
async def on_startup():
    postgres_store.init_schema()


@app.get("/")
async def root():
    return {"status": "ok", "message": "DUSD School Chatbot is running"}


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

    school_id = chat_request.school_id or config.DEFAULT_SCHOOL_ID
    agent = get_agent(school_id)
    if agent is None:
        raise HTTPException(status_code=400, detail=f"Unknown school: {school_id}")

    reply = agent.chat(chat_request.message, user_id=session_id)
    return ChatResponse(reply=reply.text, attach_map=reply.attach_map)


if __name__ == "__main__":
    print(f"Starting DUSD School Chatbot on port {config.PORT}")
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)

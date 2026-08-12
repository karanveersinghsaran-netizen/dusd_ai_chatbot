"""Unit tests for the FastAPI app in main.py: web /chat session-cookie flow."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from app.agent import ChatReply

SIGNING_KEY = "test-signing-key"


@pytest.fixture()
def client():
    main.limiter.reset()
    with patch("main.postgres_store.init_schema"), \
         patch("app.config.SESSION_SIGNING_KEY", SIGNING_KEY):
        with TestClient(main.app, base_url="https://testserver") as c:
            yield c
    main.limiter.reset()


def test_chat_without_cookie_sets_cookie(client):
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)):
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 200
    assert resp.json() == {"reply": "Hello!", "attach_map": False}
    set_cookie = resp.headers.get("set-cookie", "")
    assert "wms_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


def test_chat_with_valid_cookie_reuses_session_id(client):
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)) as mock_chat:
        client.post("/chat", json={"message": "first"})
        client.post("/chat", json={"message": "second"})

    first_session_id = mock_chat.call_args_list[0].kwargs["user_id"]
    second_session_id = mock_chat.call_args_list[1].kwargs["user_id"]
    assert first_session_id == second_session_id


def test_chat_tampered_cookie_returns_401(client):
    client.cookies.set("wms_session", "garbage.tampered")
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)):
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 401


def test_chat_ignores_client_supplied_user_id(client):
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)) as mock_chat:
        client.post("/chat", json={"message": "hi", "user_id": "attacker-controlled"})

    assert mock_chat.call_args.kwargs["user_id"] != "attacker-controlled"


# ── Server errors propagate as HTTP 5xx (not masked as 200) ─────────────────

def test_chat_returns_500_when_agent_raises_without_leaking_exception_text():
    """Downstream failures (Anthropic API unreachable, DB down, Redis stuck)
    must surface as HTTP 500 so Cloud Run's error tracker + any 5xx-based
    alerts fire. Previously the agent swallowed all exceptions and returned
    a friendly-looking HTTP 200 with the raw exception string in the body —
    great UX, terrible observability, and a minor info-disclosure smell.

    The global exception handler in main.py returns a generic body so the
    response body must NOT contain the raw exception message.

    Uses a locally-constructed client with raise_server_exceptions=False
    so the 500 is returned as a response instead of re-raising in-process."""
    main.limiter.reset()
    with patch("main.postgres_store.init_schema"), \
         patch("app.config.SESSION_SIGNING_KEY", SIGNING_KEY):
        with TestClient(main.app, base_url="https://testserver", raise_server_exceptions=False) as c:
            with patch.object(main.agent, "chat", side_effect=RuntimeError("upstream boom")):
                resp = c.post("/chat", json={"message": "hi"})
    main.limiter.reset()

    assert resp.status_code == 500
    # Body is generic — no raw exception text leaks to the client.
    assert "upstream boom" not in resp.text
    assert "Internal server error" in resp.json()["detail"]


# ── Health endpoint (Cloud Run readiness) ───────────────────────────────────

def test_root_health_endpoint_returns_200_without_touching_agent(client):
    """Cloud Run and uptime checks poll `/` — it must respond 200 without
    invoking the LLM or the database, so a downstream outage doesn't take the
    container out of the load-balancer pool."""
    with patch.object(main.agent, "chat") as mock_chat:
        resp = client.get("/")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_chat.assert_not_called()


# ── CORS ────────────────────────────────────────────────────────────────────

def test_cors_preflight_allows_configured_origin(client):
    resp = client.options(
        "/chat",
        headers={
            "origin": "https://wms.dublinusd.org",
            "access-control-request-method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://wms.dublinusd.org"


def test_cors_preflight_blocks_disallowed_origin(client):
    resp = client.options(
        "/chat",
        headers={
            "origin": "https://evil.example.com",
            "access-control-request-method": "POST",
        },
    )
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_cors_actual_request_from_disallowed_origin_gets_no_acao_header(client):
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)):
        resp = client.post(
            "/chat",
            json={"message": "hi"},
            headers={"origin": "https://evil.example.com"},
        )
    # The server still processes the request (CORS is enforced by browsers, not
    # servers, for actual requests) but omits the header that would let a
    # disallowed origin's JS read the response.
    assert "access-control-allow-origin" not in resp.headers


# ── Rate limiting ───────────────────────────────────────────────────────────

def test_eleventh_request_in_a_minute_returns_429(client):
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)):
        for _ in range(10):
            resp = client.post("/chat", json={"message": "hi"})
            assert resp.status_code == 200
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 429


# ── Request size cap ────────────────────────────────────────────────────────

def test_oversized_request_body_is_rejected(client):
    huge_message = "a" * 3000
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)) as mock_chat:
        resp = client.post("/chat", json={"message": huge_message})

    assert resp.status_code == 413
    mock_chat.assert_not_called()


def test_request_body_within_cap_is_accepted(client):
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)):
        resp = client.post("/chat", json={"message": "a" * 100})

    assert resp.status_code == 200


# ── /chatbox route (same-origin dev widget) ─────────────────────────────────

def test_chatbox_route_serves_html(client):
    resp = client.get("/chatbox")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    # Marker from chatbox.html's <title>; guards against the route silently
    # serving the wrong file.
    assert "Wells Middle School Chat" in resp.text


# ── /embed/wms-chatbot.js route (interim static hosting, pending #10) ──────────

def test_embed_script_route_serves_js(client):
    resp = client.get("/embed/wms-chatbot.js")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    # Marker from wms-chatbot.js; guards against the route silently serving
    # the wrong file.
    assert "data-api-base" in resp.text

"""Unit tests for the FastAPI app in main.py: web /chat session-cookie flow and
a regression guard that the WhatsApp webhook is unaffected."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from app.agent import ChatReply

SIGNING_KEY = "test-signing-key"


@pytest.fixture()
def client():
    with patch("main.postgres_store.init_schema"), \
         patch("app.config.SESSION_SIGNING_KEY", SIGNING_KEY):
        with TestClient(main.app, base_url="https://testserver") as c:
            yield c


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


def test_whatsapp_webhook_still_works(client):
    with patch.object(main.agent, "chat", return_value=ChatReply("Hello!", False)) as mock_chat:
        resp = client.post(
            "/webhook/whatsapp",
            data={"Body": "hi", "From": "whatsapp:+15551234567"},
        )

    assert resp.status_code == 200
    assert "Hello!" in resp.text
    assert mock_chat.call_args.kwargs["user_id"] == "whatsapp:+15551234567"

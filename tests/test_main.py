"""Unit tests for the FastAPI app in main.py: web /chat session-cookie flow."""
import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main
from app import config
from app.agent import ChatReply
from app.schools import load_schools
from app.security.chatbox_token import (
    TOKEN_EXPIRED,
    TOKEN_MALFORMED,
    TOKEN_MISSING,
    issue_chatbox_token,
)
from app.store.redis_store import RedisStore
from tests.store.conftest import FakeRedisClient

SIGNING_KEY = "test-signing-key"
CHATBOX_TOKEN_KEY = "test-chatbox-token-key"


@pytest.fixture()
def client():
    main.limiter.reset()
    # Fresh, isolated fake Redis per test: main.py's /chat handler now checks
    # the daily message cap (#71) directly against app.store.redis_store's
    # module-level `store`, which would otherwise require a live Redis
    # (unavailable in the unit-test job) and leak counters across tests.
    fake_redis_store = RedisStore(client=FakeRedisClient())
    with patch("main.postgres_store.init_schema"), \
         patch("app.config.SESSION_SIGNING_KEY", SIGNING_KEY), \
         patch("app.config.CHATBOX_TOKEN_SIGNING_KEY", CHATBOX_TOKEN_KEY), \
         patch("main.redis_store", fake_redis_store):
        with TestClient(main.app, base_url="https://testserver") as c:
            yield c
    main.limiter.reset()


def _mock_agent(reply=ChatReply("Hello!", False), side_effect=None):
    """A MagicMock standing in for a SchoolAgent instance, wired to
    patch("main.get_agent", ...)."""
    agent = MagicMock()
    if side_effect is not None:
        agent.chat.side_effect = side_effect
    else:
        agent.chat.return_value = reply
    return agent


def test_chat_without_cookie_sets_cookie(client):
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 200
    assert resp.json() == {"reply": "Hello!", "attach_map": False}
    set_cookie = resp.headers.get("set-cookie", "")
    assert "wms_session=" in set_cookie
    assert "httponly" in set_cookie.lower()
    assert "samesite=lax" in set_cookie.lower()


def test_chat_with_valid_cookie_reuses_session_id(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        client.post("/chat", json={"message": "first"})
        client.post("/chat", json={"message": "second"})

    first_session_id = mock_agent.chat.call_args_list[0].kwargs["user_id"]
    second_session_id = mock_agent.chat.call_args_list[1].kwargs["user_id"]
    assert first_session_id == second_session_id


def test_chat_tampered_cookie_returns_401(client):
    client.cookies.set("wms_session", "garbage.tampered")
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 401


def test_chat_ignores_client_supplied_user_id(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        client.post("/chat", json={"message": "hi", "user_id": "attacker-controlled"})

    assert mock_agent.chat.call_args.kwargs["user_id"] != "attacker-controlled"


# ── language toggle (#62) ────────────────────────────────────────────────────

def test_chat_forwards_language_to_agent(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        client.post("/chat", json={"message": "Hola", "language": "es"})

    assert mock_agent.chat.call_args.kwargs["language"] == "es"


def test_chat_without_language_forwards_none(client):
    """No language in the request body — e.g. an older client — must not
    crash the endpoint; SchoolAgent.chat() owns the fallback-to-persisted
    (or English) behavior from here."""
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 200
    assert mock_agent.chat.call_args.kwargs["language"] is None


# ── #51: chatbox token overrides cookie identity ────────────────────────────

def test_chat_with_token_uses_token_user_id(client):
    """A valid chatbox token's embedded user_id wins over the session
    cookie — this is what gives a Safari tab and an installed PWA opened
    from the same link a shared conversation, even though iOS gives them
    separate cookie jars."""
    mock_agent = _mock_agent()
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, user_id="admin-1")
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post(f"/chat?token={token}", json={"message": "hi"})

    assert resp.status_code == 200
    assert mock_agent.chat.call_args.kwargs["user_id"] == "admin-1"


def test_chat_without_token_falls_back_to_cookie_session_id(client):
    """No token on the request (e.g. the plain desktop-website iframe embed)
    keeps working exactly as before: identity comes from the cookie."""
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 200
    assert mock_agent.chat.call_args.kwargs["user_id"]
    assert "wms_session=" in resp.headers.get("set-cookie", "")


def test_chat_with_expired_token_falls_back_to_cookie_session_id(client):
    mock_agent = _mock_agent()
    expired = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, user_id="admin-1", days_valid=-1)
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post(f"/chat?token={expired}", json={"message": "hi"})

    assert resp.status_code == 200
    assert mock_agent.chat.call_args.kwargs["user_id"] != "admin-1"


def test_chat_with_valid_token_ignores_tampered_cookie(client):
    """A tampered cookie would normally 401 the request (see
    test_chat_tampered_cookie_returns_401) — but a valid token already
    proves identity, so a bad cookie shouldn't block the request."""
    mock_agent = _mock_agent()
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, user_id="admin-1")
    client.cookies.set("wms_session", "garbage.tampered")
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post(f"/chat?token={token}", json={"message": "hi"})

    assert resp.status_code == 200
    assert mock_agent.chat.call_args.kwargs["user_id"] == "admin-1"


def test_chat_same_token_lands_in_same_bucket_across_separate_cookie_jars(client):
    """Simulates a Safari tab and a home-screen-installed PWA: two requests
    carrying the same token but no shared cookie jar (each a fresh
    TestClient) must resolve to the same user_id — the actual #51 scenario."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, user_id="admin-1")
    mock_agent = _mock_agent()

    with patch("main.get_agent", return_value=mock_agent), \
         patch("app.config.SESSION_SIGNING_KEY", SIGNING_KEY), \
         patch("app.config.CHATBOX_TOKEN_SIGNING_KEY", CHATBOX_TOKEN_KEY):
        with TestClient(main.app, base_url="https://testserver") as safari_client:
            safari_client.post(f"/chat?token={token}", json={"message": "hi"})
        with TestClient(main.app, base_url="https://testserver") as pwa_client:
            pwa_client.post(f"/chat?token={token}", json={"message": "hi"})

    safari_user_id = mock_agent.chat.call_args_list[0].kwargs["user_id"]
    pwa_user_id = mock_agent.chat.call_args_list[1].kwargs["user_id"]
    assert safari_user_id == pwa_user_id == "admin-1"


# ── school_id routing ────────────────────────────────────────────────────────

def test_chat_without_school_id_resolves_default_school(client):
    with patch("main.get_agent", return_value=_mock_agent()) as mock_get_agent:
        client.post("/chat", json={"message": "hi"})

    mock_get_agent.assert_called_once_with("wells")


def test_chat_with_school_id_resolves_that_school(client):
    with patch("main.get_agent", return_value=_mock_agent()) as mock_get_agent:
        client.post("/chat", json={"message": "hi", "school_id": "dhs"})

    mock_get_agent.assert_called_once_with("dhs")


def test_chat_with_unknown_school_id_returns_400(client):
    with patch("main.get_agent", return_value=None):
        resp = client.post("/chat", json={"message": "hi", "school_id": "nonexistent"})

    assert resp.status_code == 400


# ── GET /chat/history: restore chat on reopen (#73) ─────────────────────────

def test_history_empty_for_fresh_session(client):
    mock_agent = _mock_agent()
    mock_agent.get_history.return_value = []
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.get("/chat/history")

    assert resp.status_code == 200
    assert resp.json() == {"messages": []}


def test_history_returns_stored_messages(client):
    mock_agent = _mock_agent()
    mock_agent.get_history.return_value = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello!"},
    ]
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.get("/chat/history")

    assert resp.status_code == 200
    assert resp.json() == {
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello!"},
        ]
    }


def test_history_uses_same_identity_as_chat(client):
    """A message sent via /chat, then fetched via /chat/history with the
    same cookie jar, must resolve to the same user_id — same
    resolve_user_id() call both endpoints share."""
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        client.post("/chat", json={"message": "hi"})
        client.get("/chat/history")

    chat_user_id = mock_agent.chat.call_args.kwargs["user_id"]
    history_user_id = mock_agent.get_history.call_args.args[0]
    assert history_user_id == chat_user_id


def test_history_passes_limit_through(client):
    mock_agent = _mock_agent()
    mock_agent.get_history.return_value = []
    with patch("main.get_agent", return_value=mock_agent):
        client.get("/chat/history?limit=5")

    assert mock_agent.get_history.call_args.kwargs["limit"] == 5


def test_history_defaults_to_wells(client):
    with patch("main.get_agent", return_value=_mock_agent()) as mock_get_agent:
        client.get("/chat/history")

    mock_get_agent.assert_called_once_with("wells")


def test_history_with_school_id_resolves_that_school(client):
    with patch("main.get_agent", return_value=_mock_agent()) as mock_get_agent:
        client.get("/chat/history?school_id=dhs")

    mock_get_agent.assert_called_once_with("dhs")


def test_history_with_unknown_school_id_returns_400(client):
    with patch("main.get_agent", return_value=None):
        resp = client.get("/chat/history?school_id=nonexistent")

    assert resp.status_code == 400


def test_history_with_token_uses_token_user_id(client):
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, user_id="admin-1")
    mock_agent = _mock_agent()
    mock_agent.get_history.return_value = []
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.get(f"/chat/history?token={token}")

    assert resp.status_code == 200
    assert mock_agent.get_history.call_args.args[0] == "admin-1"


# ── /feedback/thanks ─────────────────────────────────────────────────────────

def test_thanks_without_cookie_mints_session_and_records(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post("/feedback/thanks", json={})

    assert resp.status_code == 200
    assert "wms_session=" in resp.headers.get("set-cookie", "")
    mock_agent.record_thanks.assert_called_once()


def test_thanks_with_tampered_cookie_returns_401(client):
    client.cookies.set("wms_session", "garbage.tampered")
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/feedback/thanks", json={})

    assert resp.status_code == 401


def test_thanks_with_school_id_resolves_that_school(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent) as mock_get_agent:
        client.post("/feedback/thanks", json={"school_id": "dhs"})

    mock_get_agent.assert_called_once_with("dhs")


def test_thanks_with_unknown_school_id_returns_400(client):
    with patch("main.get_agent", return_value=None):
        resp = client.post("/feedback/thanks", json={"school_id": "nonexistent"})

    assert resp.status_code == 400


def test_thanks_with_token_uses_token_user_id(client):
    mock_agent = _mock_agent()
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, user_id="admin-1")
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post(f"/feedback/thanks?token={token}", json={})

    assert resp.status_code == 200
    assert mock_agent.record_thanks.call_args.kwargs["user_id"] == "admin-1"


# ── /feedback/report ─────────────────────────────────────────────────────────

def _report_form(**overrides):
    form = {"name": "Jamie", "email": "jamie@example.com", "message": "the phone number was wrong"}
    form.update(overrides)
    return form


def test_report_without_cookie_mints_session_and_records(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post("/feedback/report", data=_report_form())

    assert resp.status_code == 200
    assert "wms_session=" in resp.headers.get("set-cookie", "")
    mock_agent.record_report.assert_called_once()
    _, kwargs = mock_agent.record_report.call_args
    assert kwargs["name"] == "Jamie"
    assert kwargs["email"] == "jamie@example.com"
    assert kwargs["message"] == "the phone number was wrong"
    assert kwargs["screenshot"] is None


def test_report_with_tampered_cookie_returns_401(client):
    client.cookies.set("wms_session", "garbage.tampered")
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/feedback/report", data=_report_form())

    assert resp.status_code == 401


def test_report_with_token_uses_token_user_id(client):
    mock_agent = _mock_agent()
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, user_id="admin-1")
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post(f"/feedback/report?token={token}", data=_report_form())

    assert resp.status_code == 200
    assert mock_agent.record_report.call_args.kwargs["user_id"] == "admin-1"


def test_report_missing_name_returns_422(client):
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/feedback/report", data=_report_form(name=""))

    assert resp.status_code == 422


def test_report_invalid_email_returns_422(client):
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/feedback/report", data=_report_form(email="not-an-email"))

    assert resp.status_code == 422


def test_report_defaults_report_type_to_problem(client):
    """An older client that never sends report_type (or the form's default
    radio state) must still record as a problem report, not error."""
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post("/feedback/report", data=_report_form())

    assert resp.status_code == 200
    assert mock_agent.record_report.call_args.kwargs["report_type"] == "problem"


def test_report_passes_feature_report_type_through(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post("/feedback/report", data=_report_form(report_type="feature"))

    assert resp.status_code == 200
    assert mock_agent.record_report.call_args.kwargs["report_type"] == "feature"


def test_report_rejects_invalid_report_type(client):
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/feedback/report", data=_report_form(report_type="bogus"))

    assert resp.status_code == 422


def test_report_with_unknown_school_id_returns_400(client):
    with patch("main.get_agent", return_value=None):
        resp = client.post("/feedback/report", data=_report_form(school_id="nonexistent"))

    assert resp.status_code == 400


def test_report_with_valid_screenshot_passes_bytes_through(client):
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        resp = client.post(
            "/feedback/report",
            data=_report_form(),
            files={"screenshot": ("shot.png", b"\x89PNG\r\n\x1a\nfakepngbytes", "image/png")},
        )

    assert resp.status_code == 200
    _, kwargs = mock_agent.record_report.call_args
    assert kwargs["screenshot"] == b"\x89PNG\r\n\x1a\nfakepngbytes"
    assert kwargs["screenshot_content_type"] == "image/png"


def test_report_rejects_non_image_screenshot(client):
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post(
            "/feedback/report",
            data=_report_form(),
            files={"screenshot": ("shot.txt", b"not an image", "text/plain")},
        )

    assert resp.status_code == 415


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
         patch("app.config.SESSION_SIGNING_KEY", SIGNING_KEY), \
         patch("main.redis_store", RedisStore(client=FakeRedisClient())):
        with TestClient(main.app, base_url="https://testserver", raise_server_exceptions=False) as c:
            mock_agent = _mock_agent(side_effect=RuntimeError("upstream boom"))
            with patch("main.get_agent", return_value=mock_agent):
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
    with patch("main.get_agent") as mock_get_agent:
        resp = client.get("/")

    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    mock_get_agent.assert_not_called()


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


def test_cors_preflight_allows_any_dublinusd_subdomain(client):
    """CORS is matched by regex against *.dublinusd.org, not an explicit
    per-school list — so a school that isn't even in the registry yet (or any
    other DUSD subdomain) is still allowed. Onboarding a new school needs no
    CORS change."""
    resp = client.options(
        "/chat",
        headers={
            "origin": "https://not-yet-onboarded.dublinusd.org",
            "access-control-request-method": "POST",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "https://not-yet-onboarded.dublinusd.org"


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


def test_cors_preflight_blocks_dublinusd_suffix_spoofing(client):
    """The regex must be anchored — otherwise an origin merely ending in
    dublinusd.org (not actually a dublinusd.org host) would slip through."""
    resp = client.options(
        "/chat",
        headers={
            "origin": "https://dublinusd.org.evil.com",
            "access-control-request-method": "POST",
        },
    )
    assert resp.status_code == 400
    assert "access-control-allow-origin" not in resp.headers


def test_cors_actual_request_from_disallowed_origin_gets_no_acao_header(client):
    with patch("main.get_agent", return_value=_mock_agent()):
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
    with patch("main.get_agent", return_value=_mock_agent()):
        for _ in range(10):
            resp = client.post("/chat", json={"message": "hi"})
            assert resp.status_code == 200
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 429


# ── Daily message cap (#71) ─────────────────────────────────────────────────

def test_chat_within_daily_cap_succeeds(client, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 5)
    with patch("main.get_agent", return_value=_mock_agent()):
        for _ in range(2):
            resp = client.post("/chat", json={"message": "hi"})
            assert resp.status_code == 200


def test_chat_at_daily_cap_succeeds(client, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 2)
    with patch("main.get_agent", return_value=_mock_agent()):
        for _ in range(2):
            resp = client.post("/chat", json={"message": "hi"})
            assert resp.status_code == 200


def test_chat_above_daily_cap_returns_429_with_retry_after_and_friendly_message(client, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 2)
    with patch("main.get_agent", return_value=_mock_agent()):
        for _ in range(2):
            resp = client.post("/chat", json={"message": "hi"})
            assert resp.status_code == 200
        resp = client.post("/chat", json={"message": "hi"})

    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert int(resp.headers["Retry-After"]) > 0
    assert resp.json()["detail"] == (
        "You've reached today's message limit. Try again tomorrow, or contact "
        "the school office if you need help right now."
    )


def test_chat_above_daily_cap_does_not_call_the_agent(client, monkeypatch):
    """The cap must be enforced before the (billed) Claude API call, not
    after — otherwise it wouldn't be a cost guard at all."""
    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 1)
    mock_agent = _mock_agent()
    with patch("main.get_agent", return_value=mock_agent):
        client.post("/chat", json={"message": "hi"})
        client.post("/chat", json={"message": "hi"})

    assert mock_agent.chat.call_count == 1


def test_chat_daily_cap_whitelist_bypasses_the_cap(client, monkeypatch):
    from app.security.sessions import issue_session_id

    session_id, cookie_value = issue_session_id(signing_key=SIGNING_KEY)
    client.cookies.set("wms_session", cookie_value)

    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 1)
    monkeypatch.setattr(config, "DAILY_CAP_WHITELIST", {session_id})

    with patch("main.get_agent", return_value=_mock_agent()):
        for _ in range(3):
            resp = client.post("/chat", json={"message": "hi"})
            assert resp.status_code == 200


def test_chat_reply_gets_warning_note_when_approaching_cap(client, monkeypatch):
    # cap 4, WARNING_THRESHOLD 2 (app/daily_cap.py): remaining goes 3, 2, 1, 0
    # across the 4 allowed messages -> no warning, warning, warning, no
    # warning (the last allowed message doesn't warn — the *next* one just
    # gets the hard block message instead, so there's nothing new to add).
    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 4)
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/chat", json={"message": "hi"})
        assert resp.json()["reply"] == "Hello!"  # remaining=3, above threshold

        resp = client.post("/chat", json={"message": "hi"})
        assert "You have 2 messages left today." in resp.json()["reply"]

        resp = client.post("/chat", json={"message": "hi"})
        assert "You have 1 message left today." in resp.json()["reply"]

        resp = client.post("/chat", json={"message": "hi"})
        assert resp.json()["reply"] == "Hello!"  # remaining=0, last allowed message


def test_chat_reply_has_no_warning_note_with_plenty_of_headroom(client, monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 50)
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/chat", json={"message": "hi"})
    assert resp.json()["reply"] == "Hello!"


def test_chat_daily_cap_uses_school_override(client, monkeypatch):
    """A school.json daily_message_cap override takes precedence over the
    district-wide default."""
    from dataclasses import replace
    from app.schools import get_school

    monkeypatch.setattr(config, "DEFAULT_DAILY_MESSAGE_CAP", 100)
    capped_wells = replace(get_school("wells"), daily_message_cap=1)

    with patch("main.get_school", return_value=capped_wells), \
         patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/chat", json={"message": "hi"})
        assert resp.status_code == 200
        resp = client.post("/chat", json={"message": "hi"})
        assert resp.status_code == 429


# ── Request size cap ────────────────────────────────────────────────────────

def test_oversized_request_body_is_rejected(client):
    huge_message = "a" * 3000
    with patch("main.get_agent", return_value=_mock_agent()) as mock_get_agent:
        resp = client.post("/chat", json={"message": huge_message})

    assert resp.status_code == 413
    mock_get_agent.assert_not_called()


def test_request_body_within_cap_is_accepted(client):
    with patch("main.get_agent", return_value=_mock_agent()):
        resp = client.post("/chat", json={"message": "a" * 100})

    assert resp.status_code == 200


# ── /chatbox route (same-origin dev widget) ─────────────────────────────────

def test_chatbox_route_serves_html_with_valid_token(client):
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    # Marker from chatbox.html's <title>; guards against the route silently
    # serving the wrong file.
    assert "School Chat" in resp.text


def test_chatbox_route_rejects_missing_token(client):
    """Status stays 404 (semantically the resource isn't reachable), but the
    body is a friendly HTML page — installed PWAs land here after their
    embedded token expires, and the old raw JSON body ("detail: Not Found")
    made the app look broken on first launch from home screen."""
    resp = client.get("/chatbox")

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "You need an access link" in resp.text


def test_chatbox_route_rejects_expired_token(client):
    expired = issue_chatbox_token(days_valid=-1, signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={expired}")

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "expired" in resp.text.lower()


def test_chatbox_route_rejects_invalid_token_as_incomplete_not_expired(client):
    """A damaged token must NOT be reported as expired. Telling someone
    their perfectly good link lapsed sends them to request a replacement
    that will be truncated the exact same way."""
    resp = client.get("/chatbox?token=garbage")

    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "This link looks incomplete" in resp.text
    assert "has expired" not in resp.text


def test_chatbox_route_reports_markdown_mangled_generic_token_as_incomplete(client):
    """The real-world case: a generic token's user_id field is the literal
    "*" marker, and writing that link in markdown escapes it to "\\*". The
    signature then fails and the old page blamed expiry."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY, generic=True)
    resp = client.get(f"/chatbox?token={token.replace('*', chr(92) + '*')}")

    assert resp.status_code == 404
    assert "This link looks incomplete" in resp.text


def test_chatbox_route_reports_truncated_token_as_incomplete(client):
    """How a link actually breaks in a chat client or email: the tail of
    the signature is cut off."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token[:-8]}")

    assert resp.status_code == 404
    assert "This link looks incomplete" in resp.text


def test_each_link_rejection_reason_renders_its_own_copy():
    """Guards the exact-string swap in _link_unavailable_page: the EXPIRED
    block in main.py must stay byte-identical to the default already in
    link-unavailable.html, or the replace silently no-ops and every reason
    renders "expired" again — the bug this all exists to fix."""
    headings = {
        reason: re.search(r"<h1>(.*?)</h1>", main._link_unavailable_page(reason)).group(1)
        for reason in (TOKEN_EXPIRED, TOKEN_MALFORMED, TOKEN_MISSING)
    }

    assert len(set(headings.values())) == 3, headings
    assert "expired" in headings[TOKEN_EXPIRED].lower()


def test_unrecognised_link_rejection_reason_still_renders_a_page():
    """A reason added to chatbox_token.py without a block here must degrade
    to the default wording, never raise on a user-facing error path."""
    page = main._link_unavailable_page("some-future-reason")

    assert "<h1>" in page


def test_chatbox_route_injects_token_into_manifest_link(client):
    """Server-side interpolation of the manifest URL is what makes the
    installed PWA actually reopen with a valid token — relying on client-side
    JS to update the manifest href race-conditioned iOS Safari, which fetches
    the manifest early and can miss the JS update."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert f'<link rel="manifest" href="/manifest.webmanifest?token={token}">' in resp.text


# ── /chatbox route: per-school theming (#52) ────────────────────────────────

def test_chatbox_route_embeds_public_school_theme_data(client):
    """The chatbox reads school-theme-data to render per-school colors/logo
    without an extra network round trip — it must be populated with every
    school's public theme fields regardless of which (if any) is pinned."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    marker = '<script id="school-theme-data" type="application/json">'
    assert marker in resp.text
    start = resp.text.index(marker) + len(marker)
    end = resp.text.index("</script>", start)
    theme_data = json.loads(resp.text[start:end])

    assert theme_data["wells"]["name"] == "Wells Middle School"
    assert theme_data["wells"]["primary_bubble_color"] == "#00695c"
    assert theme_data["dhs"]["name"] == "Dublin High School"
    assert theme_data["dhs"]["primary_bubble_color"] == "#0a2472"
    # bell_schedule_url IS meant to leak — it's a public URL (same sensitivity
    # as school.website), exposed so the chatbox can render an always-visible
    # bell schedule link without spending an AI call on a very common question.
    assert theme_data["wells"]["bell_schedule_url"] == (
        "https://drive.google.com/file/d/1ylPRVuaMTKY0Y9_iyOqpC0nkVpmH6ZWN/view"
    )
    assert theme_data["dhs"]["bell_schedule_url"] == "https://dhs.dublinusd.org/apps/bell_schedules/"
    # Other operational fields (phone, the full bell schedule text, ...) must
    # still NOT leak into the public payload sent to the browser.
    assert "phone" not in theme_data["wells"]
    assert "bell_schedule" not in theme_data["wells"]


# ── /chatbox route: per-school "what's new" announcements ──────────────────

def test_chatbox_route_embeds_announcements_scoped_per_school(client):
    """Announcements are tagged with which school(s) they apply to
    (data/announcements.json) — the DHS-only course-catalog entry must show
    up for dhs and NOT for wells, which doesn't have that tool at all."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    marker = '<script id="announcements-data" type="application/json">'
    assert marker in resp.text
    start = resp.text.index(marker) + len(marker)
    end = resp.text.index("</script>", start)
    announcements = json.loads(resp.text[start:end])

    dhs_ids = [a["id"] for a in announcements["dhs"]]
    assert "2026-09-course-catalog" in dhs_ids
    wells_ids = [a["id"] for a in announcements["wells"]]
    assert "2026-09-course-catalog" not in wells_ids

    # An entry with no "schools" key at all (e.g. the Instagram announcement)
    # applies to every school, not just the ones with school-specific news.
    assert "2026-09-instagram" in dhs_ids
    assert "2026-09-instagram" in wells_ids


def test_public_announcements_missing_file_degrades_to_empty(client):
    """A missing/corrupt announcements.json is a nice-to-have nudge, not
    something that should ever break /chatbox from loading."""
    with patch("main.ANNOUNCEMENTS_FILE", Path("/nonexistent/announcements.json")):
        token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
        resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    marker = '<script id="announcements-data" type="application/json">'
    start = resp.text.index(marker) + len(marker)
    end = resp.text.index("</script>", start)
    announcements = json.loads(resp.text[start:end])
    assert announcements["dhs"] == []
    assert announcements["wells"] == []


def test_public_announcements_caps_at_ten_per_school(client, tmp_path):
    """A returning user should see a short 'what's changed recently' list,
    not the app's entire feature history — the popover isn't a scrollable
    archive."""
    fifteen_entries = [
        {"id": f"2026-00-{i:02d}", "date": "2026-01-01", "title": f"Feature {i}", "text": "...", "schools": ["dhs"]}
        for i in range(15)
    ]
    announcements_file = tmp_path / "announcements.json"
    announcements_file.write_text(json.dumps(fifteen_entries))

    with patch("main.ANNOUNCEMENTS_FILE", announcements_file):
        token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
        resp = client.get(f"/chatbox?token={token}")

    marker = '<script id="announcements-data" type="application/json">'
    start = resp.text.index(marker) + len(marker)
    end = resp.text.index("</script>", start)
    announcements = json.loads(resp.text[start:end])
    assert len(announcements["dhs"]) == 10
    assert announcements["dhs"][0]["id"] == "2026-00-00"
    assert announcements["dhs"][-1]["id"] == "2026-00-09"


def test_chatbox_route_appends_school_to_manifest_link_when_pinned(client):
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}&school=wells")

    assert resp.status_code == 200
    assert f'<link rel="manifest" href="/manifest.webmanifest?token={token}&school=wells">' in resp.text


def test_chatbox_route_ignores_unknown_school_in_manifest_link(client):
    """An unrecognized ?school= must not get forwarded into the manifest
    link — otherwise the manifest route would just no-op on it anyway, but
    leaving off the param keeps the link consistent with pinned-vs-not."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}&school=nonexistent")

    assert resp.status_code == 200
    assert f'<link rel="manifest" href="/manifest.webmanifest?token={token}">' in resp.text


def test_chatbox_route_swaps_apple_touch_icon_for_pinned_school(client):
    """iOS reads apple-touch-icon at page-load time, so the branded variant
    must be interpolated server-side (same rationale as the manifest link) —
    a client-side rewrite would race the browser's own icon fetch."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}&school=wells")

    assert resp.status_code == 200
    assert '<link rel="apple-touch-icon" href="/icons/apple-touch-icon-wells.png">' in resp.text
    assert '<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">' not in resp.text


def test_chatbox_route_keeps_generic_apple_touch_icon_when_unpinned(client):
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert '<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">' in resp.text


def test_chatbox_route_keeps_generic_apple_touch_icon_for_school_missing_branded_icon(client, tmp_path, monkeypatch):
    """A school onboarded without running scripts/generate_icons.py yet must
    still get a working (generic) apple-touch-icon rather than a 404 link."""
    import app.schools as schools_module

    school_dir = tmp_path / "noicon"
    school_dir.mkdir()
    school_dir.joinpath("school.json").write_text(
        json.dumps(
            {
                "id": "noicon",
                "name": "No Icon School",
                "district": "Dublin Unified School District",
                "district_id": "dusd",
                "website": "https://noicon.dublinusd.org/",
                "rss_url": "https://noicon.dublinusd.org/rss",
            }
        )
    )
    monkeypatch.setattr(schools_module, "SCHOOLS_DIR", tmp_path)
    schools_module.load_schools.cache_clear()
    try:
        token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
        resp = client.get(f"/chatbox?token={token}&school=noicon")

        assert resp.status_code == 200
        assert '<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png">' in resp.text
    finally:
        schools_module.load_schools.cache_clear()


# ── /embed/wms-chatbot.js route (interim static hosting, pending #10) ──────────

def test_embed_script_route_serves_js(client):
    resp = client.get("/embed/wms-chatbot.js")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/javascript")
    # Marker from wms-chatbot.js; guards against the route silently serving
    # the wrong file.
    assert "data-api-base" in resp.text


# ── PWA: /manifest.webmanifest + /icons/* ──────────────────────────────────

def test_manifest_route_serves_json_with_default_start_url(client):
    """Without a valid token, the manifest still serves — otherwise the PWA
    could never be installed. `start_url` falls back to bare /chatbox (which
    404s on launch until the user has a token, but that's a graceful failure
    mode vs. a broken install)."""
    resp = client.get("/manifest.webmanifest")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/manifest+json")
    body = resp.json()
    assert body["name"] == "DUSD School Chat"
    assert body["display"] == "standalone"
    assert body["start_url"] == "/chatbox"
    # Icons must be declared in three sizes for iOS + Android + maskable to
    # all resolve to a real file. Missing icons = install prompts refuse.
    icon_srcs = {i["src"] for i in body["icons"]}
    assert icon_srcs == {
        "/icons/icon-192.png",
        "/icons/icon-512.png",
        "/icons/icon-512-maskable.png",
    }


def test_manifest_route_embeds_token_in_start_url_when_valid(client):
    """When a valid token is passed, `start_url` includes it so launching the
    installed PWA from the home screen reuses the same token instead of 404ing."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/manifest.webmanifest?token={token}")

    assert resp.status_code == 200
    assert resp.json()["start_url"] == f"/chatbox?token={token}"


def test_manifest_route_ignores_invalid_token(client):
    """An invalid/tampered token silently falls back to the plain start_url —
    not an error, since the manifest itself is public and the caller isn't
    granted /chatbox access just by fetching it."""
    resp = client.get("/manifest.webmanifest?token=garbage")

    assert resp.status_code == 200
    assert resp.json()["start_url"] == "/chatbox"


# ── /manifest.webmanifest: per-school branding (#52) ────────────────────────

def test_manifest_route_returns_branded_icons_and_name_for_known_school(client):
    resp = client.get("/manifest.webmanifest?school=wells")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Wells Middle School Chat"
    assert body["short_name"] == "Wells Chat"
    assert body["theme_color"] == "#00695c"
    assert body["background_color"] == "#eef7f6"
    icon_srcs = {i["src"] for i in body["icons"]}
    assert icon_srcs == {
        "/icons/icon-192-wells.png",
        "/icons/icon-512-wells.png",
        "/icons/icon-512-maskable-wells.png",
    }


def test_manifest_route_returns_branded_icons_for_other_known_school(client):
    resp = client.get("/manifest.webmanifest?school=dhs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "Dublin High School Chat"
    assert body["theme_color"] == "#0a2472"
    icon_srcs = {i["src"] for i in body["icons"]}
    assert icon_srcs == {
        "/icons/icon-192-dhs.png",
        "/icons/icon-512-dhs.png",
        "/icons/icon-512-maskable-dhs.png",
    }


def test_manifest_route_falls_back_to_generic_for_unknown_school(client):
    resp = client.get("/manifest.webmanifest?school=nonexistent")

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "DUSD School Chat"
    icon_srcs = {i["src"] for i in body["icons"]}
    assert icon_srcs == {
        "/icons/icon-192.png",
        "/icons/icon-512.png",
        "/icons/icon-512-maskable.png",
    }


def test_manifest_route_falls_back_to_generic_icons_when_branded_set_incomplete(client, tmp_path, monkeypatch):
    """A school with theme colors but no generated icon files yet (onboarded
    before someone ran scripts/generate_icons.py) must not ship a manifest
    that references missing PNGs — installs would silently break."""
    import app.schools as schools_module

    school_dir = tmp_path / "newschool"
    school_dir.mkdir()
    school_dir.joinpath("school.json").write_text(
        json.dumps(
            {
                "id": "newschool",
                "name": "New School",
                "district": "Dublin Unified School District",
                "district_id": "dusd",
                "website": "https://newschool.dublinusd.org/",
                "rss_url": "https://newschool.dublinusd.org/rss",
                "theme_color": "#123456",
                "primary_bubble_color": "#123456",
                "background_tint": "#eeeeee",
            }
        )
    )
    monkeypatch.setattr(schools_module, "SCHOOLS_DIR", tmp_path)
    schools_module.load_schools.cache_clear()
    try:
        resp = client.get("/manifest.webmanifest?school=newschool")

        assert resp.status_code == 200
        body = resp.json()
        # Name/theme_color still apply (those don't depend on icon files)...
        assert body["name"] == "New School Chat"
        assert body["theme_color"] == "#123456"
        # ...but icons fall back to the generic set since none of the
        # icon-*-newschool.png files exist on disk.
        icon_srcs = {i["src"] for i in body["icons"]}
        assert icon_srcs == {
            "/icons/icon-192.png",
            "/icons/icon-512.png",
            "/icons/icon-512-maskable.png",
        }
    finally:
        schools_module.load_schools.cache_clear()


def test_manifest_route_appends_school_to_start_url_only_with_valid_token(client):
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/manifest.webmanifest?school=wells&token={token}")

    assert resp.status_code == 200
    assert resp.json()["start_url"] == f"/chatbox?token={token}&school=wells"


def test_manifest_route_omits_school_from_start_url_without_valid_token(client):
    resp = client.get("/manifest.webmanifest?school=wells")

    assert resp.status_code == 200
    assert resp.json()["start_url"] == "/chatbox"


def test_icon_route_serves_png(client):
    resp = client.get("/icons/icon-192.png")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    # PNG magic bytes — guards against the route silently serving the wrong file.
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_icon_route_serves_apple_touch_icon(client):
    """apple-touch-icon.png is the one iOS Safari reads for home-screen
    installs; if this 404s, the installed app gets a blank icon."""
    resp = client.get("/icons/apple-touch-icon.png")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_icon_route_rejects_missing_file(client):
    resp = client.get("/icons/nonexistent.png")

    assert resp.status_code == 404


def test_icon_route_serves_branded_school_icons(client):
    """The per-school icon variants (#52) generated by
    scripts/generate_icons.py are served through the same generic route as
    the default icons — no route change needed to add a school."""
    for filename in ("icon-192-wells.png", "icon-192-dhs.png", "apple-touch-icon-wells.png"):
        resp = client.get(f"/icons/{filename}")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"
        assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_icon_route_rejects_path_traversal(client):
    """FastAPI's path parameter normally forbids slashes, but the guard is
    also enforced in the handler for defense-in-depth against future refactors
    that might switch to a catch-all route."""
    # `../secrets` inside a single path segment — FastAPI keeps it as a
    # literal filename; the handler must still refuse to serve it.
    resp = client.get("/icons/..%2Fsecrets.png")
    assert resp.status_code == 404


def test_icon_route_rejects_non_png(client):
    """Only PNG served — prevents the route from accidentally handing out
    arbitrary files if someone drops other extensions in static/icons/."""
    resp = client.get("/icons/manifest.webmanifest")
    assert resp.status_code == 404


# ── Root-level browser-probe icon paths (/favicon.ico + apple-touch-icon-*) ──
# These aliases exist purely to stop browsers' auto-probes filling the Cloud
# Run 4xx logs with harmless 404s — real users get their icon from the
# HTML's <link> tags, not these root paths.

def test_favicon_ico_serves_png(client):
    """Browsers auto-fetch /favicon.ico on every page load. Serving the 192px
    PNG (browsers accept image/png at this path) kills the biggest source of
    4xx noise in the deployed logs."""
    resp = client.get("/favicon.ico")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize(
    "path",
    [
        "/apple-touch-icon.png",
        "/apple-touch-icon-precomposed.png",
        "/apple-touch-icon-120x120.png",
        "/apple-touch-icon-120x120-precomposed.png",
    ],
)
def test_root_apple_touch_icon_aliases_serve_png(client, path):
    """iOS Safari probes each of these paths at the root before it parses the
    HTML's <link rel="apple-touch-icon">. All four aliases must resolve to the
    same PNG so the deployed 4xx graph stops filling with iOS icon probes."""
    resp = client.get(path)

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_root_icon_aliases_are_cached(client):
    """Serve with a long cache-control so browsers don't re-fetch the same
    static asset on every page load."""
    for path in ("/favicon.ico", "/apple-touch-icon.png"):
        resp = client.get(path)
        assert "max-age" in resp.headers.get("cache-control", "")


# ── /schools/{school_id}/campus-map ──────────────────────────────────────────

def test_campus_map_route_serves_dhs_image(client):
    resp = client.get("/schools/dhs/campus-map")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/jpeg"


def test_campus_map_route_serves_wells_image(client):
    resp = client.get("/schools/wells/campus-map")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"


def test_campus_map_route_rejects_unknown_school(client):
    resp = client.get("/schools/nonexistent/campus-map")
    assert resp.status_code == 404


# ── Accessibility: /fonts/* (issue #64) ─────────────────────────────────────

def test_font_route_serves_woff2(client):
    resp = client.get("/fonts/OpenDyslexic-Regular.woff2")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "font/woff2"
    # WOFF2 magic bytes ("wOF2") — guards against the route silently serving
    # the wrong file.
    assert resp.content.startswith(b"wOF2")


def test_font_route_serves_bold_variant(client):
    resp = client.get("/fonts/OpenDyslexic-Bold.woff2")

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "font/woff2"


def test_font_route_rejects_missing_file(client):
    resp = client.get("/fonts/nonexistent.woff2")

    assert resp.status_code == 404


def test_font_route_rejects_path_traversal(client):
    """Same defense-in-depth guard as /icons/{filename}: FastAPI's path
    parameter normally forbids slashes, but the handler still refuses to
    serve anything that isn't a plain filename."""
    resp = client.get("/fonts/..%2Fsecrets.woff2")
    assert resp.status_code == 404


def test_font_route_rejects_non_woff2(client):
    """Only .woff2 served — prevents the route from accidentally handing out
    arbitrary files if something else lands in static/fonts/."""
    resp = client.get("/fonts/OpenDyslexic-OFL.txt")
    assert resp.status_code == 404


def test_version_endpoint_returns_the_app_version(client):
    resp = client.get("/version")

    assert resp.status_code == 200
    assert resp.json() == {"version": main.APP_VERSION}


def test_responses_carry_x_app_version_header(client):
    """The chatbox detects a new deploy via this header on ordinary /chat
    responses (checkAppVersion() in chatbox.html), not by polling /version —
    any response missing it silently breaks that detection. Asserted against
    a route with nothing to do with versioning, so this fails if the header
    stops being applied globally by the middleware — hitting /version here
    would still pass if only that one route set it."""
    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.headers["X-App-Version"] == main.APP_VERSION


def test_chatbox_route_embeds_app_version(client):
    """The version active when this page was rendered must be embedded so
    the update-banner logic (checkAppVersion() in chatbox.html) has something
    to compare a later response's X-App-Version header against."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    marker = '<script id="app-version-data" type="application/json">'
    assert marker in resp.text
    start = resp.text.index(marker) + len(marker)
    end = resp.text.index("</script>", start)
    assert json.loads(resp.text[start:end]) == {"version": main.APP_VERSION}


def test_chatbox_html_has_update_banner(client):
    """Guards against the "update available" banner (#update-banner) and its
    refresh/dismiss wiring silently disappearing from the served HTML."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert 'id="update-banner"' in resp.text
    assert 'id="update-banner-btn"' in resp.text
    assert "wireUpdateBanner" in resp.text


def test_chatbox_html_links_to_manifest_and_apple_touch_icon(client):
    """The HTML must actually reference the PWA manifest + apple-touch-icon —
    without these tags, no browser will offer an "Install" prompt regardless
    of what /manifest.webmanifest returns."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert '<link rel="manifest"' in resp.text
    assert 'apple-touch-icon' in resp.text
    assert 'apple-mobile-web-app-capable' in resp.text


def test_chatbox_html_has_theme_toggle_and_help_button(client):
    """Guards against the light/dark toggle and help/support button silently
    disappearing from the served HTML."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert 'id="theme-toggle-btn"' in resp.text
    assert 'id="help-btn"' in resp.text
    assert 'id="report-open-btn"' in resp.text
    assert 'id="thanks-btn"' in resp.text
    assert 'id="clear-btn"' in resp.text


def test_chatbox_html_has_instagram_link(client):
    """Guards against the "Follow us on Instagram" menu row silently
    disappearing from the served HTML."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert 'href="https://www.instagram.com/dusdchat/"' in resp.text


def test_chatbox_html_has_accessibility_settings_panel(client):
    """Guards against the accessibility settings button/panel (issue #64)
    silently disappearing from the served HTML — the four required controls
    (font, text size, contrast, motion) must all be present."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert 'id="a11y-settings-btn"' in resp.text
    assert 'id="a11y-panel"' in resp.text
    assert 'name="a11y-font"' in resp.text
    assert 'name="a11y-text-size"' in resp.text
    assert 'name="a11y-contrast"' in resp.text
    assert 'name="a11y-motion"' in resp.text


def test_chatbox_html_has_language_toggle(client):
    """Guards against the EN/ES/中文 language toggle (#62) silently
    disappearing from the served HTML."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert 'id="lang-toggle-btn"' in resp.text


def test_chatbox_html_has_ai_disclaimer(client):
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    resp = client.get(f"/chatbox?token={token}")

    assert resp.status_code == 200
    assert 'id="disclaimer"' in resp.text
    assert "AI can make mistakes" in resp.text


# ── school picker is driven by the school data, not hardcoded (#173) ───────

def test_chatbox_does_not_hardcode_school_radio_buttons():
    """The picker listed wells and dhs as literal <input> tags, so onboarding
    Fallon and Emerald left them unreachable from it even though every
    backend endpoint served them. Nothing in the suite noticed, because the
    picker is markup. Build it from the school data instead."""
    markup = Path(main.__file__).parent.joinpath("chatbox.html").read_text(encoding="utf-8")

    assert 'name="school" value=' not in markup, (
        "school radios are hardcoded again — build them from school-theme-data"
    )


def test_chatbox_theme_data_covers_every_school(client):
    """Whatever the picker renders comes from this island, so every school
    under data/schools/ has to appear in it."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    body = client.get(f"/chatbox?token={token}").text

    island = re.search(
        r'<script id="school-theme-data"[^>]*>(.*?)</script>', body, re.S).group(1)
    themes = json.loads(island)

    assert set(themes) == set(load_schools()), (
        f"chatbox exposes {sorted(themes)} but data/schools has {sorted(load_schools())}"
    )
    # A name is what the picker label and header are derived from.
    assert all(t.get("name") for t in themes.values())


def test_chatbox_theme_data_exposes_each_school_level(client):
    """The Middle/High dropdowns are built from this field, so it has to
    reach the page — the picker can't group schools it can't categorise."""
    token = issue_chatbox_token(signing_key=CHATBOX_TOKEN_KEY)
    body = client.get(f"/chatbox?token={token}").text

    themes = json.loads(re.search(
        r'<script id="school-theme-data"[^>]*>(.*?)</script>', body, re.S).group(1))

    assert {t["level"] for t in themes.values()} == {"middle", "high"}


def test_chatbox_renders_a_level_dropdown_per_level_not_hardcoded_schools():
    """Guards the shape of the picker: selects keyed by data-level, built in
    script, with no school id written into the markup."""
    markup = Path(main.__file__).parent.joinpath("chatbox.html").read_text(encoding="utf-8")

    assert 'name="school" value=' not in markup
    assert 'data-level' in markup
    # The active school is marked by a radio inside each level row, so the
    # school a question goes to is stated once rather than repeated in a
    # separate row that re-listed every name.
    assert '"active-school"' in markup

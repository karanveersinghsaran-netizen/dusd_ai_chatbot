import json
from typing import Optional

import redis

from app import config

CONV_TTL_SECONDS = 24 * 60 * 60           # 24h, refreshed on every append
LAST_RESPONSE_TTL_SECONDS = 24 * 60 * 60  # tied to conversation lifetime
FEEDBACK_ASKED_TTL_SECONDS = 24 * 60 * 60 # "ask once" window
PENDING_TTL_SECONDS = 30 * 60             # window for user to answer 1/2 or a report comment
MAX_HISTORY = 20


def _conv_key(session_id: str) -> str:
    return f"wms:conv:{session_id}"


def _last_response_key(session_id: str) -> str:
    return f"wms:last_response:{session_id}"


def _feedback_asked_key(session_id: str) -> str:
    return f"wms:feedback_asked:{session_id}"


def _feedback_pending_key(session_id: str) -> str:
    return f"wms:feedback_pending:{session_id}"


def _report_pending_key(session_id: str) -> str:
    return f"wms:report_pending:{session_id}"


class RedisStore:
    def __init__(self, client: Optional[redis.Redis] = None):
        self.client = client or redis.Redis.from_url(config.REDIS_URL, decode_responses=True)

    # ── conversation history ────────────────────────────────────────────────
    def get_conversation(self, session_id: str) -> list:
        raw = self.client.get(_conv_key(session_id))
        return json.loads(raw) if raw else []

    def append_message(self, session_id: str, message: dict) -> None:
        history = self.get_conversation(session_id)
        history.append(message)
        if len(history) > MAX_HISTORY:
            history = history[-MAX_HISTORY:]
        self.client.setex(_conv_key(session_id), CONV_TTL_SECONDS, json.dumps(history))

    def clear_conversation(self, session_id: str) -> None:
        self.client.delete(_conv_key(session_id))

    # ── last bot response (for report attachment) ──────────────────────────
    def get_last_response(self, session_id: str) -> Optional[str]:
        return self.client.get(_last_response_key(session_id))

    def set_last_response(self, session_id: str, text: str) -> None:
        self.client.setex(_last_response_key(session_id), LAST_RESPONSE_TTL_SECONDS, text)

    def clear_last_response(self, session_id: str) -> None:
        self.client.delete(_last_response_key(session_id))

    # ── boolean-ish flags (formerly process-wide sets) ─────────────────────
    def is_feedback_asked(self, session_id: str) -> bool:
        return bool(self.client.exists(_feedback_asked_key(session_id)))

    def mark_feedback_asked(self, session_id: str) -> None:
        self.client.setex(_feedback_asked_key(session_id), FEEDBACK_ASKED_TTL_SECONDS, "1")

    def clear_feedback_asked(self, session_id: str) -> None:
        self.client.delete(_feedback_asked_key(session_id))

    def is_feedback_pending(self, session_id: str) -> bool:
        return bool(self.client.exists(_feedback_pending_key(session_id)))

    def mark_feedback_pending(self, session_id: str) -> None:
        self.client.setex(_feedback_pending_key(session_id), PENDING_TTL_SECONDS, "1")

    def clear_feedback_pending(self, session_id: str) -> None:
        self.client.delete(_feedback_pending_key(session_id))

    def is_report_pending(self, session_id: str) -> bool:
        return bool(self.client.exists(_report_pending_key(session_id)))

    def mark_report_pending(self, session_id: str) -> None:
        self.client.setex(_report_pending_key(session_id), PENDING_TTL_SECONDS, "1")

    def clear_report_pending(self, session_id: str) -> None:
        self.client.delete(_report_pending_key(session_id))

    # ── convenience ──────────────────────────────────────────────────────────
    def clear_session(self, session_id: str) -> None:
        """Delete conversation, last_response, and all pending/asked flags for a session."""
        self.client.delete(
            _conv_key(session_id),
            _last_response_key(session_id),
            _feedback_asked_key(session_id),
            _feedback_pending_key(session_id),
            _report_pending_key(session_id),
        )


store = RedisStore()

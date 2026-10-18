import json
from typing import Optional

import redis

from app import config

CONV_TTL_SECONDS = 5 * 24 * 60 * 60       # 5d (#51), refreshed on every append
LAST_RESPONSE_TTL_SECONDS = 24 * 60 * 60  # tied to conversation lifetime
FEEDBACK_ASKED_TTL_SECONDS = 24 * 60 * 60 # "ask once" window
PENDING_TTL_SECONDS = 30 * 60             # window for user to answer 1/2
LANGUAGE_TTL_SECONDS = 24 * 60 * 60       # tied to session cookie lifetime (#62)
MAX_HISTORY = 100



def _drop_orphaned_tool_results(history: list) -> list:
    """Trim leading messages until the first one can legally start a request.

    History now holds tool_use/tool_result pairs (#161), and the Anthropic API
    rejects a tool_result whose matching tool_use isn't present. Slicing to the
    last MAX_HISTORY messages can cut between the two, leaving a tool_result
    first — which would 400 every request for the rest of that session's life,
    long after the turn that caused it. Dropping from the front until the
    pairing is sound costs a message or two of context and cannot fail.
    """
    def is_tool_result(message: dict) -> bool:
        content = message.get("content")
        return (
            message.get("role") == "user"
            and isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        )

    start = 0
    while start < len(history) and is_tool_result(history[start]):
        start += 1
    # The mirror case — a trailing tool_use with no result — can't arise:
    # chat() appends each pair together and always follows them with the
    # assistant's final text, so the last message is never a bare tool_use.
    return history[start:]

def _conv_key(session_id: str) -> str:
    return f"wms:conv:{session_id}"


def _conv_count_key(session_id: str) -> str:
    """Total messages ever appended to this session, uncapped — unlike the
    conversation itself, this is never trimmed to MAX_HISTORY, so comparing
    the two tells us whether earlier history has been dropped (see
    conversation_was_truncated())."""
    return f"wms:conv_count:{session_id}"


def _last_response_key(session_id: str) -> str:
    return f"wms:last_response:{session_id}"


def _feedback_asked_key(session_id: str) -> str:
    return f"wms:feedback_asked:{session_id}"


def _feedback_pending_key(session_id: str) -> str:
    return f"wms:feedback_pending:{session_id}"


def _msgcount_key(user_id: str, day: str) -> str:
    return f"wms:msgcount:{user_id}:{day}"


def _language_key(session_id: str) -> str:
    return f"wms:lang:{session_id}"


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
            history = _drop_orphaned_tool_results(history[-MAX_HISTORY:])
        self.client.setex(_conv_key(session_id), CONV_TTL_SECONDS, json.dumps(history))
        # Uncapped running count, same TTL/refresh behavior as the
        # conversation itself — see conversation_was_truncated().
        count_key = _conv_count_key(session_id)
        self.client.incr(count_key)
        self.client.expire(count_key, CONV_TTL_SECONDS)

    def conversation_was_truncated(self, session_id: str) -> bool:
        """True once more messages have ever been appended to this session
        than MAX_HISTORY retains — i.e. earlier history has been dropped and
        is no longer visible in get_conversation(). Lets the agent tell the
        model so it can say "I only keep recent conversation" honestly
        instead of guessing when asked about something older."""
        raw = self.client.get(_conv_count_key(session_id))
        return int(raw) > MAX_HISTORY if raw else False

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

    # ── daily message cap (#71) ─────────────────────────────────────────────
    def increment_daily_message_count(self, user_id: str, day: str, ttl_seconds: int) -> int:
        """Atomically increments the message counter for user_id on the given
        Pacific calendar day (YYYY-MM-DD) and returns the new count. TTL is
        set only on the increment that creates the key (count == 1) so later
        calls the same day don't keep pushing the expiry forward — it always
        lands at end-of-day-Pacific relative to when the counter was first
        touched, per the ttl_seconds the caller computed via
        app.timezone_utils.seconds_until_pacific_midnight."""
        key = _msgcount_key(user_id, day)
        count = self.client.incr(key)
        if count == 1:
            self.client.expire(key, ttl_seconds)
        return count

    def get_daily_message_count(self, user_id: str, day: str) -> int:
        raw = self.client.get(_msgcount_key(user_id, day))
        return int(raw) if raw else 0

    # ── preferred language (#62) ────────────────────────────────────────────
    def get_preferred_language(self, session_id: str) -> Optional[str]:
        return self.client.get(_language_key(session_id))

    def set_preferred_language(self, session_id: str, language: str) -> None:
        self.client.setex(_language_key(session_id), LANGUAGE_TTL_SECONDS, language)

    # ── convenience ──────────────────────────────────────────────────────────
    def clear_session(self, session_id: str) -> None:
        """Delete conversation, last_response, and all pending/asked flags for a
        session. Deliberately leaves the preferred-language key alone — like
        the session_id itself, a language choice is a user preference that
        should survive a "clear" (which resets conversation *content*, not
        identity/settings), not something a fresh chat should reset."""
        self.client.delete(
            _conv_key(session_id),
            _conv_count_key(session_id),
            _last_response_key(session_id),
            _feedback_asked_key(session_id),
            _feedback_pending_key(session_id),
        )


store = RedisStore()

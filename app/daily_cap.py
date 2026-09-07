"""Per-user daily message cap (#71) — a cost/abuse guard for the /chat
endpoint.

Tracks a Redis counter keyed by (session id, Pacific calendar day) via
app.store.redis_store, capped per-school (falling back to a district-wide
default in app.config), with a TTL that expires the counter at the next
Pacific midnight (app.timezone_utils, from #66) regardless of what timezone
the server itself runs in. Staff/testing accounts can be exempted entirely
via the DAILY_CAP_WHITELIST env var (app.config).

Web is currently the only client — user identity is the signed session
cookie minted in app/security/sessions.py. (The original issue also
mentions a WhatsApp phone-number identity; that integration was removed
from this codebase before this was implemented, so it doesn't apply here.)
"""
import logging
from dataclasses import dataclass
from typing import Optional

from app import config
from app.schools import SchoolConfig
from app.store.redis_store import RedisStore
from app.store.redis_store import store as default_redis_store
from app.timezone_utils import pacific_now, seconds_until_pacific_midnight

logger = logging.getLogger(__name__)

FRIENDLY_CAP_MESSAGE = (
    "You've reached today's message limit. Try again tomorrow, or contact "
    "the school office if you need help right now."
)

# How many messages of headroom left before we start warning the user they're
# about to hit the cap. Small and fixed rather than a percentage of the
# per-school limit — "2 left" reads the same whether the cap is 5 (testing)
# or 20 (production), and stays a light touch rather than nagging on every
# message once someone's partway through their day.
WARNING_THRESHOLD = 2


@dataclass(frozen=True)
class DailyCapResult:
    allowed: bool
    limit: int
    count: int
    retry_after_seconds: int

    @property
    def remaining(self) -> int:
        return max(self.limit - self.count, 0)

    @property
    def approaching_limit(self) -> bool:
        return self.allowed and 0 < self.remaining <= WARNING_THRESHOLD


def daily_cap_for_school(school: Optional[SchoolConfig]) -> int:
    """Per-user daily message cap for a school: its own override
    (school.json's daily_message_cap) if set, else the district-wide
    default."""
    if school is not None and school.daily_message_cap is not None:
        return school.daily_message_cap
    return config.DEFAULT_DAILY_MESSAGE_CAP


def is_whitelisted(user_id: str) -> bool:
    """True if user_id (the session id) is exempt from the daily cap —
    staff/testing accounts listed in config.DAILY_CAP_WHITELIST."""
    return user_id in config.DAILY_CAP_WHITELIST


def check_and_increment(
    user_id: str,
    school: Optional[SchoolConfig],
    redis_store: Optional[RedisStore] = None,
) -> DailyCapResult:
    """Increments today's message count for user_id and reports whether the
    request is within the cap.

    Whitelisted users are never counted or capped — always allowed, with
    count/retry_after reported as 0. Every other call increments the Redis
    counter first and checks the result against the limit, so the count
    returned always reflects this request (including the one that first
    crosses the cap)."""
    redis_store = redis_store or default_redis_store
    limit = daily_cap_for_school(school)

    if is_whitelisted(user_id):
        return DailyCapResult(allowed=True, limit=limit, count=0, retry_after_seconds=0)

    now = pacific_now()
    day = now.date().isoformat()
    ttl_seconds = seconds_until_pacific_midnight(now)

    count = redis_store.increment_daily_message_count(user_id, day, ttl_seconds)
    allowed = count <= limit
    if not allowed:
        logger.warning(
            "daily_message_cap_hit user_id=%s school_id=%s limit=%d count=%d",
            user_id,
            school.id if school else None,
            limit,
            count,
        )
    return DailyCapResult(allowed=allowed, limit=limit, count=count, retry_after_seconds=ttl_seconds)

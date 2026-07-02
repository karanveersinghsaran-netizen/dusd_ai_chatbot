"""Integration tests for RedisStore against a real Redis container.

Requires Docker. Run with `pytest -m integration` (or the default full suite, which
includes these). Skip locally without Docker via `pytest -m "not integration"`.
"""
import pytest
from testcontainers.redis import RedisContainer

from app.store.redis_store import RedisStore

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def redis_container():
    with RedisContainer("redis:7-alpine") as container:
        yield container


@pytest.fixture()
def redis_store(redis_container):
    client = redis_container.get_client(decode_responses=True)
    store = RedisStore(client=client)
    yield store
    client.flushall()


def test_conversation_roundtrip_against_real_redis(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "hi"})
    redis_store.append_message("u1", {"role": "assistant", "content": "hello"})

    assert redis_store.get_conversation("u1") == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_conversation_ttl_is_set(redis_store, redis_container):
    redis_store.append_message("u1", {"role": "user", "content": "hi"})
    client = redis_container.get_client(decode_responses=True)
    ttl = client.ttl("wms:conv:u1")
    assert 0 < ttl <= 24 * 60 * 60


def test_flags_persist_across_store_instances(redis_store, redis_container):
    """Simulates two replicas sharing the same Redis — a second RedisStore instance
    backed by a fresh client must see state written by the first."""
    redis_store.mark_feedback_pending("u1")

    other_client = redis_container.get_client(decode_responses=True)
    other_store = RedisStore(client=other_client)
    assert other_store.is_feedback_pending("u1") is True


def test_clear_session_against_real_redis(redis_store):
    redis_store.append_message("u1", {"role": "user", "content": "hi"})
    redis_store.set_last_response("u1", "answer")
    redis_store.mark_feedback_asked("u1")

    redis_store.clear_session("u1")

    assert redis_store.get_conversation("u1") == []
    assert redis_store.get_last_response("u1") is None
    assert redis_store.is_feedback_asked("u1") is False

"""Integration tests for PostgresStore against a real Postgres container.

Requires Docker. Run with `pytest -m integration` (or the default full suite, which
includes these). Skip locally without Docker via `pytest -m "not integration"`.
"""
import psycopg
import pytest
from testcontainers.postgres import PostgresContainer

from app.store.postgres_store import PostgresStore

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_container():
    with PostgresContainer("postgres:16-alpine") as container:
        yield container


@pytest.fixture()
def postgres_store(postgres_container):
    dsn = postgres_container.get_connection_url(driver=None)
    store = PostgresStore(dsn=dsn)
    store.init_schema()
    yield store
    with psycopg.connect(dsn) as conn:
        conn.execute("TRUNCATE TABLE feedback")
        conn.commit()


def test_init_schema_is_idempotent(postgres_store):
    postgres_store.init_schema()
    postgres_store.init_schema()


def test_record_feedback_inserts_row(postgres_store):
    postgres_store.record_feedback(
        school_id="wells",
        session_hash="abc123",
        feedback_type="report",
        sentiment="negative",
        raw="the phone number seemed wrong",
        comment="please fix",
        last_response="Here's the number...",
    )

    with psycopg.connect(postgres_store.dsn) as conn:
        row = conn.execute(
            "SELECT school_id, session_hash, type, sentiment, raw, comment, last_response "
            "FROM feedback WHERE session_hash = %s",
            ("abc123",),
        ).fetchone()

    assert row == (
        "wells",
        "abc123",
        "report",
        "negative",
        "the phone number seemed wrong",
        "please fix",
        "Here's the number...",
    )


def test_record_feedback_optional_fields_default_null(postgres_store):
    postgres_store.record_feedback(
        school_id="wells", session_hash="xyz789", feedback_type="passive", sentiment="positive", raw="1",
    )

    with psycopg.connect(postgres_store.dsn) as conn:
        row = conn.execute(
            "SELECT comment, last_response FROM feedback WHERE session_hash = %s",
            ("xyz789",),
        ).fetchone()

    assert row == (None, None)

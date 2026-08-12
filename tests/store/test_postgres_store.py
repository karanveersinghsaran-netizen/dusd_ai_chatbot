"""Unit tests for PostgresStore (app/store/postgres_store.py) — psycopg is mocked."""
from unittest.mock import MagicMock, patch

from app.store.postgres_store import PostgresStore


@patch("app.store.postgres_store.psycopg.connect")
def test_init_schema_executes_ddl(mock_connect):
    mock_conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn

    store = PostgresStore(dsn="postgresql://fake")
    store.init_schema()

    assert mock_conn.execute.call_count == 1
    ddl = mock_conn.execute.call_args[0][0]
    assert "CREATE TABLE IF NOT EXISTS feedback" in ddl
    mock_conn.commit.assert_called_once()


@patch("app.store.postgres_store.psycopg.connect")
def test_record_feedback_inserts_expected_row(mock_connect):
    mock_conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn

    store = PostgresStore(dsn="postgresql://fake")
    store.record_feedback(
        school_id="wells",
        session_hash="abc123",
        feedback_type="report",
        sentiment="negative",
        raw="the phone number seemed wrong",
        comment="please fix",
        last_response="Here's the number...",
    )

    mock_conn.execute.assert_called_once()
    sql, params = mock_conn.execute.call_args[0]
    assert "INSERT INTO feedback" in sql
    assert params == (
        "wells",
        "abc123",
        "report",
        "negative",
        "the phone number seemed wrong",
        "please fix",
        "Here's the number...",
    )
    mock_conn.commit.assert_called_once()


@patch("app.store.postgres_store.psycopg.connect")
def test_record_feedback_empty_optional_fields_become_none(mock_connect):
    mock_conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn

    store = PostgresStore(dsn="postgresql://fake")
    store.record_feedback(
        school_id="wells",
        session_hash="abc123",
        feedback_type="passive",
        sentiment="positive",
        raw="1",
    )

    _, params = mock_conn.execute.call_args[0]
    assert params[5] is None  # comment
    assert params[6] is None  # last_response


@patch("app.store.postgres_store.psycopg.connect")
def test_record_feedback_uses_explicit_school_id(mock_connect):
    mock_conn = MagicMock()
    mock_connect.return_value.__enter__.return_value = mock_conn

    store = PostgresStore(dsn="postgresql://fake")
    store.record_feedback(
        school_id="dhs", session_hash="abc123", feedback_type="passive", sentiment="positive", raw="1",
    )

    _, params = mock_conn.execute.call_args[0]
    assert params[0] == "dhs"

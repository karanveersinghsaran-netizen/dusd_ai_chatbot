from pathlib import Path
from typing import Optional

import psycopg

from app import config

_SCHEMA_FILE = Path(__file__).resolve().parents[2] / "db" / "schema.sql"


class PostgresStore:
    def __init__(self, dsn: Optional[str] = None):
        self.dsn = dsn or config.DATABASE_URL

    def init_schema(self) -> None:
        """Idempotent; executes db/schema.sql. Call once at app startup."""
        ddl = _SCHEMA_FILE.read_text(encoding="utf-8")
        with psycopg.connect(self.dsn) as conn:
            conn.execute(ddl)
            conn.commit()

    def record_feedback(
        self,
        school_id: str,
        session_hash: str,
        feedback_type: str,
        sentiment: str,
        raw: str,
        comment: str = "",
        last_response: str = "",
        name: str = "",
        email: str = "",
        screenshot: Optional[bytes] = None,
        screenshot_content_type: str = "",
    ) -> None:
        with psycopg.connect(self.dsn) as conn:
            conn.execute(
                """
                INSERT INTO feedback
                    (school_id, session_hash, type, sentiment, raw, comment, last_response,
                     name, email, screenshot, screenshot_content_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    school_id,
                    session_hash,
                    feedback_type,
                    sentiment,
                    raw,
                    comment or None,
                    last_response or None,
                    name or None,
                    email or None,
                    screenshot,
                    screenshot_content_type or None,
                ),
            )
            conn.commit()


store = PostgresStore()

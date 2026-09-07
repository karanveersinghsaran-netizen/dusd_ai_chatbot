CREATE TABLE IF NOT EXISTS feedback (
    id BIGSERIAL PRIMARY KEY,
    school_id TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    type TEXT NOT NULL,              -- 'passive' | 'thanks' | 'report'
    sentiment TEXT NOT NULL,         -- 'positive' | 'negative'
    raw TEXT NOT NULL,
    comment TEXT,
    last_response TEXT,
    name TEXT,
    email TEXT,
    screenshot BYTEA,
    screenshot_content_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Idempotent migrations for the report form (name/email/screenshot) — the
-- CREATE above only fires on a fresh database, so existing ones need these.
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS name TEXT;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS email TEXT;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS screenshot BYTEA;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS screenshot_content_type TEXT;

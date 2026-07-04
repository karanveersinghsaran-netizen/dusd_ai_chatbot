CREATE TABLE IF NOT EXISTS feedback (
    id BIGSERIAL PRIMARY KEY,
    school_id TEXT NOT NULL,
    session_hash TEXT NOT NULL,
    type TEXT NOT NULL,              -- 'passive' | 'report'
    sentiment TEXT NOT NULL,         -- 'positive' | 'negative'
    raw TEXT NOT NULL,
    comment TEXT,
    last_response TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Personal notes for the developer account.
-- Stored per-user (developer only), no school_id needed.

CREATE TABLE IF NOT EXISTS developer_notes (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT 'default',
    is_pinned   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_developer_notes_user_id
    ON developer_notes(user_id);

CREATE INDEX IF NOT EXISTS idx_developer_notes_pinned
    ON developer_notes(user_id, is_pinned DESC, updated_at DESC);

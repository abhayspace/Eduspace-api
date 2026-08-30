-- Force-update flag: when TRUE, all users see a popup telling them to update
-- the app.  The developer toggles this from the developer home tab.

CREATE TABLE IF NOT EXISTS app_force_update (
    id INTEGER PRIMARY KEY DEFAULT 1,
    force_update BOOLEAN NOT NULL DEFAULT FALSE,
    message TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT single_row CHECK (id = 1)
);

INSERT INTO app_force_update (id, force_update, message)
VALUES (1, FALSE, NULL)
ON CONFLICT (id) DO NOTHING;

-- Free trial support: mark schools as trial, track trial period and admin contact.
ALTER TABLE schools ADD COLUMN IF NOT EXISTS is_trial BOOLEAN DEFAULT FALSE;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS trial_starts_at TIMESTAMPTZ;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS trial_ends_at TIMESTAMPTZ;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS trial_admin_name TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS trial_phone TEXT;
ALTER TABLE schools ADD COLUMN IF NOT EXISTS trial_status TEXT DEFAULT 'active';
-- trial_status: 'active' | 'expired' | 'converted' | 'stopped'

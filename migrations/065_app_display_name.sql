-- App display name shown in the app header/home for users logged in with
-- this institution code.  Falls back to "Eduspace" when NULL/empty so the
-- default experience is unchanged until an admin customises it.

ALTER TABLE schools
    ADD COLUMN IF NOT EXISTS app_display_name TEXT;

-- When TRUE the app shows the school's uploaded logo (logo_url) as the
-- app icon.  When FALSE (default) the app shows the default Eduspace icon.
ALTER TABLE schools
    ADD COLUMN IF NOT EXISTS use_school_logo BOOLEAN NOT NULL DEFAULT FALSE;

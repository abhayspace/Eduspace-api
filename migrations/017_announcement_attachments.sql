alter table announcements
    add column if not exists attachment_url text,
    add column if not exists attachment_name text,
    add column if not exists recipient_user_id uuid,
    add column if not exists recipient_name text,
    add column if not exists recipient_type text;

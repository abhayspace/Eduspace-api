-- Chat message photo/video attachments.

alter table messages
    add column if not exists media_url text,
    add column if not exists media_type text,
    add column if not exists media_name text;

alter table messages
    drop constraint if exists messages_media_type_check;

-- NOT VALID: existing rows may already contain 'file' (allowed by 031), which
-- would fail validation when this migration is re-run on an existing database.
alter table messages
    add constraint messages_media_type_check
    check (media_type is null or media_type in ('image', 'video')) not valid;

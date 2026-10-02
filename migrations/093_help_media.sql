-- Media attachments on help chat messages.
-- Users can attach an image when messaging "Help Center"; the developer sees
-- it in the help inbox. Nullable — existing text-only messages are untouched.

alter table help_messages
    add column if not exists media_url  text,
    add column if not exists media_type varchar(20),
    add column if not exists media_name text;

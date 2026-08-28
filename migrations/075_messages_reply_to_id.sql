-- Add reply_to_id column to messages table for message replies.
-- The messages router already selects this column but it was never created
-- in the database, causing 500 Internal Server Error when loading conversations.

alter table messages
    add column if not exists reply_to_id uuid references messages (id) on delete set null;

create index if not exists idx_messages_reply_to_id
    on messages (reply_to_id)
    where reply_to_id is not null;

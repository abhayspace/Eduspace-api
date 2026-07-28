-- Group chat messages (class-section / manual groups).
-- recipient_id stays a user UUID for DMs; group threads use group_id instead.

alter table messages
    add column if not exists group_id text;

create index if not exists idx_messages_group
    on messages (school_id, group_id, created_at desc)
    where group_id is not null;

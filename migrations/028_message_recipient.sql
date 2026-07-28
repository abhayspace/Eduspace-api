-- Direct messages: optional recipient on school chat messages.

alter table messages
    add column if not exists recipient_id uuid references users (id) on delete set null;

create index if not exists idx_messages_recipient
    on messages (school_id, recipient_id, created_at desc);

create index if not exists idx_messages_sender_recipient
    on messages (school_id, sender_id, recipient_id, created_at desc);

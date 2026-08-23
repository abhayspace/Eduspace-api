-- Help chat between users and the developer.
-- Users send messages from the "Need Help?" screen; the developer replies
-- from the developer help inbox. No email is sent — all communication is
-- in-app.

create table if not exists help_messages (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid        not null references users (id) on delete cascade,
    sender       varchar     not null,  -- 'user' | 'developer'
    sender_label text        not null,  -- e.g. "Ravi - ADM123 (ABCDEF)"
    message      text        not null,
    created_at   timestamptz not null default now()
);

create index if not exists idx_help_messages_user on help_messages (user_id, created_at);
create index if not exists idx_help_messages_created on help_messages (created_at desc);

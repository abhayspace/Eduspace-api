-- Per-user "delete for me" support on chat messages.

alter table messages
    add column if not exists hidden_for uuid[] not null default '{}';

create index if not exists idx_messages_hidden_for
    on messages using gin (hidden_for);

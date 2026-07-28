-- Chat messages: rolling 1-year retention per school (enforced in application code).

comment on table messages is 'School chat / direct messages; application retains 1 year per school.';

-- Range scans for retention purge and year-scoped thread/history reads.
create index if not exists idx_messages_school_created_range
    on messages (school_id, created_at desc);

create index if not exists idx_messages_school_sender_created
    on messages (school_id, sender_id, created_at desc);

create index if not exists idx_messages_school_recipient_created
    on messages (school_id, recipient_id, created_at desc)
    where recipient_id is not null;

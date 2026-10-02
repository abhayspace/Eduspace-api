-- School "apply for free trial" requests submitted from the onboarding join card.

create table if not exists school_join_requests (
    id          uuid primary key default gen_random_uuid(),
    school_name varchar     not null,
    email       varchar     not null,
    contact     varchar     not null,
    address     varchar     not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists school_join_requests_created_idx
    on school_join_requests (created_at desc);

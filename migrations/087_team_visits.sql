-- Team school visits: members log which school they plan to visit and when;
-- the whole team can see everyone's plan, and the visitor marks it done.

create table if not exists team_visits (
    id          uuid primary key default gen_random_uuid(),
    member_id   uuid        not null references team_members(id) on delete cascade,
    member_name varchar     not null default '',
    school_name varchar     not null default '',
    visit_date  varchar     not null default '',
    note        varchar     not null default '',
    done        boolean     not null default false,
    created_at  timestamptz not null default now()
);

create index if not exists team_visits_all_idx
    on team_visits (done, created_at desc);

-- Payment ledger + contribution log for team members.
-- Admin adds entries per member; member's earnings/contributions fields stay
-- in sync as rollups of these rows.

create table if not exists team_payments (
    id          uuid primary key default gen_random_uuid(),
    member_id   uuid        not null references team_members(id) on delete cascade,
    member_name varchar     not null default '',
    amount      varchar     not null default '',
    note        text        not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists team_payments_member_idx
    on team_payments (member_id, created_at desc);

create table if not exists team_contributions (
    id          uuid primary key default gen_random_uuid(),
    member_id   uuid        not null references team_members(id) on delete cascade,
    member_name varchar     not null default '',
    text        text        not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists team_contributions_member_idx
    on team_contributions (member_id, created_at desc);

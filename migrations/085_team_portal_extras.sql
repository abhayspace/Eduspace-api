-- Team portal extras: per-member contributions/earnings (developer-written)
-- and a log of every email a team member sends through the portal.

alter table team_members
    add column if not exists contributions text not null default '',
    add column if not exists earnings      text not null default '';

create table if not exists team_emails (
    id          uuid primary key default gen_random_uuid(),
    member_id   uuid        not null references team_members(id) on delete cascade,
    school_name varchar     not null default '',
    to_email    varchar     not null,
    subject     varchar     not null default '',
    cc          text        not null default '',
    bcc         text        not null default '',
    description text        not null default '',
    attachment  varchar     not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists team_emails_member_idx
    on team_emails (member_id, created_at desc);

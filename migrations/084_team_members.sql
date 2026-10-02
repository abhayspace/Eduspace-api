-- Team member accounts for the TEAM01 institution code (internal team portal).
-- Team members are platform-level accounts (not scoped to a school) that can
-- send branded email to registered schools and open the school registration form.

create table if not exists team_members (
    id            uuid primary key default gen_random_uuid(),
    full_name     varchar     not null,
    username      varchar     not null,
    email         varchar     not null,
    password_hash text        not null,
    is_active     boolean     not null default true,
    created_at    timestamptz not null default now()
);

create unique index if not exists uq_team_members_username on team_members (lower(username));
create unique index if not exists uq_team_members_email on team_members (lower(email));

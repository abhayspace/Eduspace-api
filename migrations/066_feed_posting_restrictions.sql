-- School Feed: admins can restrict a person from creating new feed posts.
-- Existing posts remain visible; only new post creation is blocked.

create table if not exists feed_posting_restrictions (
    id            uuid        primary key default gen_random_uuid(),
    school_id     uuid        not null references schools (id) on delete cascade,
    user_id       uuid        not null references users (id) on delete cascade,
    restricted_by uuid        not null references users (id) on delete set null,
    reason        text        not null default '',
    created_at    timestamptz not null default now(),
    unique (school_id, user_id)
);

create index if not exists idx_feed_posting_restrictions_school
    on feed_posting_restrictions (school_id, user_id);

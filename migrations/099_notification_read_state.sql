-- Per-user "seen up to" timestamp for the synthesized notification feed items.
create table if not exists notification_read_state (
  user_id uuid primary key references users(id) on delete cascade,
  school_id uuid not null references schools(id) on delete cascade,
  last_seen_at timestamptz not null default now()
);

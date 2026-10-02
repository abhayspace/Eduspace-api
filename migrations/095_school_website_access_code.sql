-- Website access code for school administrators.
alter table schools
  add column if not exists web_access_code_hash text,
  add column if not exists web_access_code_created_at timestamptz,
  add column if not exists web_access_code_created_by uuid references users(id) on delete set null;

alter table users
  add column if not exists web_access_only boolean not null default false;

create index if not exists idx_users_web_access_only
  on users (school_id, web_access_only)
  where web_access_only;

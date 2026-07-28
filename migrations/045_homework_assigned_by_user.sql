-- Homework: track assigning teacher for "mine only" list/edit/delete.

alter table homework
    add column if not exists assigned_by_user_id uuid references users (id) on delete set null;

create index if not exists idx_homework_assigned_by_user
    on homework (school_id, assigned_by_user_id, created_at desc);

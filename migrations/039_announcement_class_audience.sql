-- Class/section targeting for announcements (audience = 'class').
alter table announcements
    add column if not exists audience_targets jsonb not null default '{}'::jsonb;

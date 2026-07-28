alter table announcements
    add column if not exists recipients jsonb not null default '[]'::jsonb;

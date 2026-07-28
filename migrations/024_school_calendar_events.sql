create table if not exists school_calendar_events (
    id           uuid primary key default gen_random_uuid(),
    school_id    uuid        not null references schools (id) on delete cascade,
    event_type   text        not null check (event_type in ('holiday', 'birthday', 'special_day')),
    title        text        not null,
    description  text,
    event_date   date        not null,
    end_date     date,
    created_by   text,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

create index if not exists idx_school_calendar_events_school_date
    on school_calendar_events (school_id, event_date);

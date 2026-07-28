-- School-wide hours and per-class period timetables.

create table if not exists school_timing (
    school_id       uuid primary key references schools (id) on delete cascade,
    start_time      text        not null default '',
    start_meridiem  text        not null default 'AM' check (start_meridiem in ('AM', 'PM')),
    end_time        text        not null default '',
    end_meridiem    text        not null default 'PM' check (end_meridiem in ('AM', 'PM')),
    updated_at      timestamptz not null default now()
);

create table if not exists period_timetables (
    id            uuid primary key default gen_random_uuid(),
    school_id     uuid        not null references schools (id) on delete cascade,
    period_count  int         not null check (period_count > 0),
    times_saved   boolean     not null default false,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);

create index if not exists idx_period_timetables_school
    on period_timetables (school_id, updated_at desc);

create table if not exists period_timetable_classes (
    id            uuid primary key default gen_random_uuid(),
    timetable_id  uuid not null references period_timetables (id) on delete cascade,
    class_id      uuid not null,
    class_name    text not null,
    unique (timetable_id, class_id)
);

create index if not exists idx_period_timetable_classes_timetable
    on period_timetable_classes (timetable_id);

create table if not exists period_timetable_slots (
    id              uuid primary key default gen_random_uuid(),
    timetable_id    uuid not null references period_timetables (id) on delete cascade,
    period_index    int  not null check (period_index >= 0),
    start_time      text not null default '',
    start_meridiem  text not null default 'AM' check (start_meridiem in ('AM', 'PM')),
    end_time        text not null default '',
    end_meridiem    text not null default 'AM' check (end_meridiem in ('AM', 'PM')),
    unique (timetable_id, period_index)
);

create index if not exists idx_period_timetable_slots_timetable
    on period_timetable_slots (timetable_id, period_index);

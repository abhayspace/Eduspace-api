-- Substitute class assignments for teachers during free periods.

create table if not exists teacher_substitute_assignments (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools (id) on delete cascade,
    teacher_id      uuid not null references teachers (id) on delete cascade,
    class_id        uuid not null,
    section_id      uuid not null,
    period_index    int  not null check (period_index >= 0),
    subject_name    text not null default '',
    created_at      timestamptz not null default now(),
    unique (teacher_id, period_index)
);

create index if not exists idx_teacher_substitute_assignments_teacher
    on teacher_substitute_assignments (school_id, teacher_id);

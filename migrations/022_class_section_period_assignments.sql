-- Per-section subject and teacher for each period.

create table if not exists class_section_period_assignments (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools (id) on delete cascade,
    class_id        uuid not null,
    section_id      uuid not null,
    period_index    int  not null check (period_index >= 0),
    subject_id      uuid references subjects (id) on delete set null,
    subject_name    text not null default '',
    teacher_id      uuid references teachers (id) on delete set null,
    teacher_name    text not null default '',
    updated_at      timestamptz not null default now(),
    unique (section_id, period_index)
);

create index if not exists idx_class_section_period_assignments_section
    on class_section_period_assignments (section_id, period_index);

create index if not exists idx_class_section_period_assignments_class
    on class_section_period_assignments (school_id, class_id);

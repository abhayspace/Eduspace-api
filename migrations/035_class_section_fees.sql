-- Monthly fee schedule per class section (section override of class default).
create table if not exists class_section_fees (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid           not null references schools (id) on delete cascade,
    class_id        uuid           not null references classes (id) on delete cascade,
    section_id      uuid           not null references sections (id) on delete cascade,
    monthly_amount  numeric(12, 2) not null check (monthly_amount >= 0),
    created_at      timestamptz    not null default now(),
    updated_at      timestamptz    not null default now(),
    unique (school_id, section_id)
);

create index if not exists idx_class_section_fees_school
    on class_section_fees (school_id);
create index if not exists idx_class_section_fees_class
    on class_section_fees (school_id, class_id);

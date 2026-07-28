-- Academic tables required for Classes screen (safe to re-run).
create extension if not exists "pgcrypto";

create table if not exists classes (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    name        text        not null,
    grade_level text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_classes_school on classes (school_id);

create table if not exists sections (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    class_id   uuid        references classes (id) on delete cascade,
    name       text        not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_sections_school on sections (school_id);
create index if not exists idx_sections_class on sections (class_id);

create table if not exists subjects (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    name       text        not null,
    code       text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists idx_subjects_school on subjects (school_id);

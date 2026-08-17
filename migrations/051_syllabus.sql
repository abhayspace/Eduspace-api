-- Class syllabus: one entry per class-section, split into terms with chapters.

create table if not exists syllabi (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    class_id            uuid        not null references classes (id) on delete cascade,
    section_id          uuid        not null references sections (id) on delete cascade,
    class_name          text        not null default '',
    section_name        text        not null default '',
    created_by_user_id  uuid        references users (id) on delete set null,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    unique (school_id, class_id, section_id)
);
create index if not exists idx_syllabi_school on syllabi (school_id);

create table if not exists syllabus_terms (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    syllabus_id uuid        not null references syllabi (id) on delete cascade,
    name        text        not null,
    sort_order  integer     not null default 0,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_syllabus_terms_syllabus on syllabus_terms (syllabus_id, sort_order);

create table if not exists syllabus_chapters (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    term_id     uuid        not null references syllabus_terms (id) on delete cascade,
    title       text        not null,
    description text        not null default '',
    sort_order  integer     not null default 0,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_syllabus_chapters_term on syllabus_chapters (term_id, sort_order);

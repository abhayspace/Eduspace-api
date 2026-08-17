-- School medical room visits logged against a teacher's own medical record.

create table if not exists teacher_medical_visits (
    id            uuid primary key default gen_random_uuid(),
    school_id     uuid        not null references schools (id) on delete cascade,
    user_id       uuid        not null references users (id) on delete cascade,
    teacher_id    uuid        references teachers (id) on delete cascade,
    visit_date    date        not null,
    visit_time    text        not null default '',
    issue         text        not null default '',
    treatment     text        not null default '',
    prescription  text        not null default '',
    attended_by   text        not null default '',
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);
create index if not exists idx_teacher_medical_visits_school on teacher_medical_visits (school_id);
create index if not exists idx_teacher_medical_visits_user
    on teacher_medical_visits (school_id, user_id, visit_date desc);

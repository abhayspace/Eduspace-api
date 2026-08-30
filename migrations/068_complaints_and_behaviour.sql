-- Complaints & Behaviour Management system.
-- Stores complaints (submitted by students/parents/teachers/admins) and
-- behaviour records (created by teachers/admins for students).
-- IDs are TEXT (frontend-generated) for complaints, UUID for behaviour records.

-- ---------------------------------------------------------------------------
-- Complaints
-- ---------------------------------------------------------------------------
create table if not exists complaints (
    id                  text primary key,
    school_id           uuid        not null references schools (id) on delete cascade,
    title               text        not null default '',
    description         text        not null default '',
    category            text        not null default 'other',
    severity            text        not null default 'low',
    status              text        not null default 'pending',
    is_anonymous        boolean     not null default false,
    incident_date       date,
    submitted_by_user_id uuid       references users (id) on delete set null,
    submitted_by_name   text        not null default '',
    submitted_by_role   text        not null default '',
    student_id          uuid        references students (id) on delete set null,
    student_name        text        not null default '',
    involved_user_id    uuid        references users (id) on delete set null,
    involved_name       text        not null default '',
    assigned_to_user_id uuid        references users (id) on delete set null,
    assigned_to_name    text        not null default '',
    resolution_notes    text        not null default '',
    attachment_url      text,
    attachment_name     text,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_complaints_school on complaints (school_id);
create index if not exists idx_complaints_school_status on complaints (school_id, status);
create index if not exists idx_complaints_submitted_by on complaints (submitted_by_user_id);
create index if not exists idx_complaints_student on complaints (student_id);
create index if not exists idx_complaints_assigned on complaints (assigned_to_user_id);

-- ---------------------------------------------------------------------------
-- Complaint activity log (timeline of status changes, notes, assignments)
-- ---------------------------------------------------------------------------
create table if not exists complaint_activity (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    complaint_id        text        not null references complaints (id) on delete cascade,
    action              text        not null default '',
    description         text        not null default '',
    actor_user_id       uuid        references users (id) on delete set null,
    actor_name          text        not null default '',
    actor_role          text        not null default '',
    is_internal         boolean     not null default false,
    created_at          timestamptz not null default now()
);
create index if not exists idx_complaint_activity_complaint on complaint_activity (complaint_id);
create index if not exists idx_complaint_activity_school on complaint_activity (school_id);

-- ---------------------------------------------------------------------------
-- Behaviour records
-- ---------------------------------------------------------------------------
create table if not exists behaviour_records (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    student_id          uuid        not null references students (id) on delete cascade,
    student_name        text        not null default '',
    class_name          text        not null default '',
    section_name        text        not null default '',
    type                text        not null default 'positive',
    category            text        not null default 'other',
    description         text        not null default '',
    severity            text        not null default 'low',
    incident_date       date,
    recorded_by_user_id uuid        references users (id) on delete set null,
    recorded_by_name    text        not null default '',
    recorded_by_role    text        not null default '',
    is_visible_to_student boolean   not null default true,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_behaviour_school on behaviour_records (school_id);
create index if not exists idx_behaviour_student on behaviour_records (student_id);
create index if not exists idx_behaviour_school_type on behaviour_records (school_id, type);
create index if not exists idx_behaviour_recorded_by on behaviour_records (recorded_by_user_id);

-- ---------------------------------------------------------------------------
-- Disciplinary actions (linked to behaviour records or standalone)
-- ---------------------------------------------------------------------------
create table if not exists disciplinary_actions (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    student_id          uuid        not null references students (id) on delete cascade,
    student_name        text        not null default '',
    behaviour_record_id uuid        references behaviour_records (id) on delete set null,
    action_type         text        not null default 'warning',
    notes               text        not null default '',
    status              text        not null default 'pending',
    action_date         date,
    created_by_user_id  uuid        references users (id) on delete set null,
    created_by_name     text        not null default '',
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_disciplinary_school on disciplinary_actions (school_id);
create index if not exists idx_disciplinary_student on disciplinary_actions (student_id);

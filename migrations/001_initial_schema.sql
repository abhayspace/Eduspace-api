-- EduSpace — initial PostgreSQL schema (Supabase).
-- All tables use UUID primary keys, foreign keys, timestamps and indexes.
-- Authentication is handled by the FastAPI backend (JWT); Supabase is used
-- purely as PostgreSQL storage, so password hashes live in `users`.

create extension if not exists "pgcrypto";

-- ---------------------------------------------------------------------------
-- Core tenant tables
-- ---------------------------------------------------------------------------
create table if not exists schools (
    id                uuid primary key default gen_random_uuid(),
    institution_code  varchar     not null unique,
    school_name       varchar     not null,
    school_type       varchar,
    board             varchar,
    academic_session  varchar,
    email             varchar,
    phone             varchar,
    website           varchar,
    address           text,
    city              varchar,
    state             varchar,
    country           varchar,
    pincode           varchar,
    principal_name    varchar,
    logo_url          text,
    subscription_plan varchar     not null default 'free',
    is_active         boolean     not null default true,
    created_at        timestamptz not null default now()
);
create index if not exists idx_schools_institution_code on schools (institution_code);

create table if not exists users (
    id                   uuid primary key default gen_random_uuid(),
    school_id            uuid        not null references schools (id) on delete cascade,
    role                 varchar     not null,
    full_name            varchar     not null,
    email                varchar     not null,
    mobile               varchar,
    admission_no         varchar,
    user_code            varchar,
    password_hash        text        not null,
    must_change_password boolean     not null default false,
    is_active            boolean     not null default true,
    created_at           timestamptz not null default now()
);
create unique index if not exists uq_users_school_email on users (school_id, lower(email));
create index if not exists idx_users_school on users (school_id);
create index if not exists idx_users_role on users (school_id, role);
create index if not exists idx_users_admission_no on users (school_id, admission_no);
create index if not exists idx_users_user_code on users (school_id, user_code);

-- ---------------------------------------------------------------------------
-- Academic structure
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- People profiles (linked to users)
-- ---------------------------------------------------------------------------
create table if not exists students (
    id            uuid primary key default gen_random_uuid(),
    school_id     uuid        not null references schools (id) on delete cascade,
    user_id       uuid        references users (id) on delete cascade,
    admission_no  text,
    class_id      uuid        references classes (id) on delete set null,
    section_id    uuid        references sections (id) on delete set null,
    roll_no       text,
    created_at    timestamptz not null default now(),
    updated_at    timestamptz not null default now()
);
create index if not exists idx_students_school on students (school_id);
create index if not exists idx_students_user on students (user_id);

create table if not exists teachers (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    user_id     uuid        references users (id) on delete cascade,
    employee_no text,
    department  text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_teachers_school on teachers (school_id);
create index if not exists idx_teachers_user on teachers (user_id);

create table if not exists parents (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    user_id     uuid        references users (id) on delete cascade,
    student_id  uuid        references students (id) on delete set null,
    relation    text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_parents_school on parents (school_id);
create index if not exists idx_parents_user on parents (user_id);
create index if not exists idx_parents_student on parents (student_id);

-- ---------------------------------------------------------------------------
-- Operational tables
-- ---------------------------------------------------------------------------
create table if not exists attendance (
    id            uuid primary key default gen_random_uuid(),
    school_id     uuid        not null references schools (id) on delete cascade,
    student_email text        not null,
    class_name    text,
    date          date        not null,
    status        text        not null,
    marked_by     text,
    created_at    timestamptz not null default now()
);
create index if not exists idx_attendance_school on attendance (school_id);
create index if not exists idx_attendance_student on attendance (school_id, student_email);

create table if not exists homework (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    subject     text        not null,
    title       text        not null,
    description text        not null default '',
    class_name  text        not null,
    due_date    date        not null,
    assigned_by text        not null,
    created_at  timestamptz not null default now()
);
create index if not exists idx_homework_school on homework (school_id);
create index if not exists idx_homework_due on homework (school_id, due_date);

create table if not exists fees (
    id            uuid primary key default gen_random_uuid(),
    school_id     uuid        not null references schools (id) on delete cascade,
    student_email text        not null,
    title         text        not null,
    amount        numeric(12,2) not null default 0,
    due_date      date,
    status        text        not null default 'pending',
    paid_at       timestamptz,
    created_at    timestamptz not null default now()
);
create index if not exists idx_fees_school on fees (school_id);
create index if not exists idx_fees_student on fees (school_id, student_email);

create table if not exists payments (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    fee_id     uuid        references fees (id) on delete set null,
    amount     numeric(12,2) not null default 0,
    method     text,
    reference  text,
    paid_at    timestamptz not null default now(),
    created_at timestamptz not null default now()
);
create index if not exists idx_payments_school on payments (school_id);
create index if not exists idx_payments_fee on payments (fee_id);

create table if not exists timetable (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    class_name text        not null,
    day        text        not null,
    start_time text        not null,
    end_time   text        not null,
    subject    text        not null,
    teacher    text        not null,
    room       text        not null default '',
    created_at timestamptz not null default now()
);
create index if not exists idx_timetable_school on timetable (school_id);
create index if not exists idx_timetable_class on timetable (school_id, class_name);

create table if not exists examinations (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    name       text        not null,
    term       text,
    class_name text,
    subject    text,
    exam_date  date,
    max_marks  numeric(8,2) not null default 100,
    created_at timestamptz not null default now()
);
create index if not exists idx_examinations_school on examinations (school_id);

create table if not exists results (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid        not null references schools (id) on delete cascade,
    examination_id  uuid        references examinations (id) on delete cascade,
    student_email   text        not null,
    marks_obtained  numeric(8,2) not null default 0,
    grade           text,
    created_at      timestamptz not null default now()
);
create index if not exists idx_results_school on results (school_id);
create index if not exists idx_results_exam on results (examination_id);
create index if not exists idx_results_student on results (school_id, student_email);

create table if not exists announcements (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    title      text        not null,
    body       text        not null,
    audience   text        not null default 'all',
    author     text        not null default 'EduSpace',
    created_at timestamptz not null default now()
);
create index if not exists idx_announcements_school on announcements (school_id);
create index if not exists idx_announcements_created on announcements (school_id, created_at desc);

create table if not exists messages (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    sender_id   uuid        not null,
    sender_name text        not null,
    sender_role text        not null,
    text        text        not null,
    created_at  timestamptz not null default now()
);
create index if not exists idx_messages_school on messages (school_id);
create index if not exists idx_messages_created on messages (school_id, created_at desc);

create table if not exists notifications (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    user_id    uuid        references users (id) on delete cascade,
    title      text        not null,
    body       text        not null default '',
    data       jsonb       not null default '{}'::jsonb,
    is_read    boolean     not null default false,
    created_at timestamptz not null default now()
);
create index if not exists idx_notifications_school on notifications (school_id);
create index if not exists idx_notifications_user on notifications (user_id);

-- Device push-token registrations (used by POST /api/register-push).
create table if not exists device_tokens (
    id           uuid primary key default gen_random_uuid(),
    user_id      uuid        not null references users (id) on delete cascade,
    platform     text        not null,
    device_token text        not null,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now(),
    unique (user_id, device_token)
);
create index if not exists idx_device_tokens_user on device_tokens (user_id);

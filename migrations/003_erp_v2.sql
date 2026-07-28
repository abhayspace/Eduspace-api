-- EduSpace ERP V2 — extended profiles, staff attendance, class teacher constraints.

-- User profile fields
alter table users add column if not exists gender varchar;
alter table users add column if not exists dob date;
alter table users add column if not exists address text;
alter table users add column if not exists photo_url text;

-- Teacher profile extensions
alter table teachers add column if not exists gender varchar;
alter table teachers add column if not exists qualification text;
alter table teachers add column if not exists experience_years integer;
alter table teachers add column if not exists joining_date date;
alter table teachers add column if not exists photo_url text;
alter table teachers add column if not exists subjects jsonb not null default '[]'::jsonb;
alter table teachers add column if not exists classes_teaching jsonb not null default '[]'::jsonb;
alter table teachers add column if not exists is_class_teacher boolean not null default false;
alter table teachers add column if not exists class_teacher_class_id uuid references classes (id) on delete set null;
alter table teachers add column if not exists class_teacher_section_id uuid references sections (id) on delete set null;

-- Student profile extensions
alter table students add column if not exists gender varchar;
alter table students add column if not exists dob date;
alter table students add column if not exists father_name text;
alter table students add column if not exists mother_name text;
alter table students add column if not exists guardian_mobile text;
alter table students add column if not exists address text;
alter table students add column if not exists photo_url text;
alter table students add column if not exists admission_date date;

-- Non-teaching staff profiles
create table if not exists staff_profiles (
    id                uuid primary key default gen_random_uuid(),
    school_id         uuid        not null references schools (id) on delete cascade,
    user_id           uuid        references users (id) on delete cascade,
    employee_no       text,
    gender            varchar,
    dob               date,
    address           text,
    photo_url         text,
    qualification     text,
    experience_years  integer,
    joining_date      date,
    department        text,
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
);
create index if not exists idx_staff_profiles_school on staff_profiles (school_id);
create index if not exists idx_staff_profiles_user on staff_profiles (user_id);

-- Staff attendance (separate from student attendance)
create table if not exists staff_attendance (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid        not null references schools (id) on delete cascade,
    user_id    uuid        not null references users (id) on delete cascade,
    date       date        not null,
    status     text        not null,
    marked_by  text,
    created_at timestamptz not null default now(),
    unique (school_id, user_id, date)
);
create index if not exists idx_staff_attendance_school on staff_attendance (school_id);
create index if not exists idx_staff_attendance_date on staff_attendance (school_id, date);

-- One class teacher per class-section
create unique index if not exists uq_class_teacher_assignment
    on teachers (school_id, class_teacher_class_id, class_teacher_section_id)
    where is_class_teacher = true
      and class_teacher_class_id is not null
      and class_teacher_section_id is not null;

-- Link student attendance to user when available
alter table attendance add column if not exists student_id uuid references users (id) on delete set null;

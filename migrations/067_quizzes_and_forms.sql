-- Quizzes and Forms: teacher-created quizzes/forms that students can take/fill.
-- IDs are TEXT so the frontend-generated document IDs are preserved across publish.

create table if not exists quizzes (
    id                  text primary key,
    school_id           uuid        not null references schools (id) on delete cascade,
    created_by_user_id  uuid        references users (id) on delete set null,
    title               text        not null default '',
    description         text        not null default '',
    subject             text        not null default '',
    class_id            uuid        references classes (id) on delete set null,
    class_name          text        not null default '',
    section_id          uuid        references sections (id) on delete set null,
    section_name        text        not null default '',
    chapter             text        not null default '',
    instructions        text        not null default '',
    cover_image_uri     text,
    difficulty          text        not null default 'medium',
    visibility          text        not null default 'private',
    start_at            timestamptz,
    end_at              timestamptz,
    settings            jsonb       not null default '{}'::jsonb,
    questions           jsonb       not null default '[]'::jsonb,
    status              text        not null default 'draft',
    published_at        timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_quizzes_school on quizzes (school_id);
create index if not exists idx_quizzes_school_class_section
    on quizzes (school_id, class_id, section_id);
create index if not exists idx_quizzes_status on quizzes (school_id, status);

create table if not exists quiz_attempts (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    quiz_id             text        not null references quizzes (id) on delete cascade,
    student_user_id     uuid        not null references users (id) on delete cascade,
    student_name        text        not null default '',
    class_name          text        not null default '',
    section_name        text        not null default '',
    subject             text        not null default '',
    answers             jsonb       not null default '[]'::jsonb,
    score               numeric     not null default 0,
    max_score           numeric     not null default 0,
    percentage          numeric     not null default 0,
    correct_count       int         not null default 0,
    wrong_count         int         not null default 0,
    skipped_count       int         not null default 0,
    passed              boolean     not null default false,
    time_taken_seconds  int         not null default 0,
    started_at          timestamptz,
    submitted_at        timestamptz not null default now(),
    unique (quiz_id, student_user_id)
);
create index if not exists idx_quiz_attempts_school on quiz_attempts (school_id);
create index if not exists idx_quiz_attempts_quiz on quiz_attempts (quiz_id);
create index if not exists idx_quiz_attempts_student on quiz_attempts (student_user_id);

create table if not exists forms (
    id                  text primary key,
    school_id           uuid        not null references schools (id) on delete cascade,
    created_by_user_id  uuid        references users (id) on delete set null,
    title               text        not null default '',
    description         text        not null default '',
    settings            jsonb       not null default '{}'::jsonb,
    questions           jsonb       not null default '[]'::jsonb,
    status              text        not null default 'draft',
    published_at        timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_forms_school on forms (school_id);
create index if not exists idx_forms_status on forms (school_id, status);

create table if not exists form_responses (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    form_id             text        not null references forms (id) on delete cascade,
    student_user_id     uuid        not null references users (id) on delete cascade,
    student_name        text        not null default '',
    answers             jsonb       not null default '[]'::jsonb,
    submitted_at        timestamptz not null default now(),
    unique (form_id, student_user_id)
);
create index if not exists idx_form_responses_school on form_responses (school_id);
create index if not exists idx_form_responses_form on form_responses (form_id);
create index if not exists idx_form_responses_student on form_responses (student_user_id);

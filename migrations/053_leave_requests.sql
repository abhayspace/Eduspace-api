-- Leave requests: teachers, staff, and students submit requests; the school
-- (school_admin/principal/vice_principal) reviews and approves/rejects them.

create table if not exists leave_requests (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    user_id             uuid        not null references users (id) on delete cascade,
    user_name           text        not null default '',
    user_role           text        not null default '',
    title               text        not null,
    leave_type          text        not null default 'single',
    start_date          date        not null,
    end_date            date        not null,
    description         text        not null default '',
    status              text        not null default 'pending',
    reviewed_by_user_id uuid        references users (id) on delete set null,
    reviewed_at         timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint leave_requests_type_check check (leave_type in ('single', 'multiple')),
    constraint leave_requests_status_check check (status in ('pending', 'approved', 'rejected'))
);

create index if not exists idx_leave_requests_school on leave_requests (school_id, created_at desc);
create index if not exists idx_leave_requests_user on leave_requests (user_id, created_at desc);

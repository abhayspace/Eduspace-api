-- Appointments: students request appointments with principal/vice_principal;
-- the school (school_admin/principal/vice_principal) reviews and approves/rejects them.

create table if not exists appointments (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    user_id             uuid        not null references users (id) on delete cascade,
    user_name           text        not null default '',
    user_role           text        not null default '',
    title               text        not null,
    requested_with      text        not null default 'principal',
    appointment_date    date        not null,
    appointment_time     text        not null default '',
    description         text        not null default '',
    status              text        not null default 'pending',
    reviewed_by_user_id uuid        references users (id) on delete set null,
    reviewed_at         timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    constraint appointments_requested_with_check check (requested_with in ('principal', 'vice_principal')),
    constraint appointments_status_check check (status in ('pending', 'approved', 'rejected', 'cancelled'))
);

create index if not exists idx_appointments_school on appointments (school_id, created_at desc);
create index if not exists idx_appointments_user on appointments (user_id, created_at desc);

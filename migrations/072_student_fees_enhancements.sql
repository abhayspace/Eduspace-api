-- Student fees enhancements: track original amounts for partial payments,
-- discounts/scholarships/concessions, and fee notices/announcements.

-- ---------------------------------------------------------------------------
-- Track original fee amount so partial payments can show "Partially Paid".
-- When a custom partial payment is made, the fees.amount is reduced but
-- original_amount retains the initial value for display.
-- ---------------------------------------------------------------------------
alter table fees
    add column if not exists original_amount numeric(12, 2);

-- Backfill original_amount from amount for existing rows.
update fees set original_amount = amount where original_amount is null;

-- ---------------------------------------------------------------------------
-- Fee discounts / scholarships / concessions per student.
-- ---------------------------------------------------------------------------
create table if not exists fee_discounts (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools (id) on delete cascade,
    student_id      uuid references students (id) on delete cascade,
    student_email   text,
    discount_type   text not null default 'concession'
                        check (discount_type in ('discount', 'scholarship', 'concession')),
    name            text not null,
    description     text,
    original_amount numeric(12, 2) not null default 0,
    discount_amount numeric(12, 2) not null default 0,
    final_amount    numeric(12, 2) not null default 0,
    reason          text,
    authorized_by   uuid references users (id) on delete set null,
    is_active       boolean not null default true,
    valid_from      date,
    valid_to        date,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists idx_fee_discounts_school on fee_discounts (school_id);
create index if not exists idx_fee_discounts_student on fee_discounts (school_id, student_id);
create index if not exists idx_fee_discounts_email on fee_discounts (school_id, student_email);
create index if not exists idx_fee_discounts_active on fee_discounts (school_id, is_active);

-- ---------------------------------------------------------------------------
-- Fee notices / announcements (reminders, due date extensions, new charges).
-- ---------------------------------------------------------------------------
create table if not exists fee_notices (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools (id) on delete cascade,
    title           text not null,
    body            text,
    notice_type     text not null default 'reminder'
                        check (notice_type in ('reminder', 'due_date_extension', 'new_charge', 'general')),
    priority        text not null default 'normal'
                        check (priority in ('low', 'normal', 'high', 'urgent')),
    target_class_id uuid references classes (id) on delete cascade,
    target_section_id uuid references sections (id) on delete cascade,
    is_pinned       boolean not null default false,
    is_active       boolean not null default true,
    published_at    timestamptz not null default now(),
    expires_at      timestamptz,
    created_by      uuid references users (id) on delete set null,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create index if not exists idx_fee_notices_school on fee_notices (school_id);
create index if not exists idx_fee_notices_active on fee_notices (school_id, is_active);
create index if not exists idx_fee_notices_published on fee_notices (school_id, published_at desc);
create index if not exists idx_fee_notices_class on fee_notices (school_id, target_class_id);

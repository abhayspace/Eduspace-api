-- School savings entries (expenses tracker).

create table if not exists expense_savings (
    id         uuid primary key default gen_random_uuid(),
    school_id  uuid           not null references schools (id) on delete cascade,
    title      text           not null,
    amount     numeric(12, 2) not null,
    saved_date date           not null default current_date,
    created_by text,
    created_at timestamptz    not null default now(),
    constraint expense_savings_amount_check check (amount > 0)
);

create index if not exists idx_expense_savings_school
    on expense_savings (school_id);

create index if not exists idx_expense_savings_school_date
    on expense_savings (school_id, saved_date desc, created_at desc);

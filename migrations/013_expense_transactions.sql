-- School expense / income transactions (expenses tracker).

create table if not exists expense_transactions (
    id               uuid primary key default gen_random_uuid(),
    school_id        uuid           not null references schools (id) on delete cascade,
    title            text           not null,
    amount           numeric(12, 2) not null default 0,
    type             text           not null,
    transaction_date date           not null default current_date,
    notes            text,
    created_by       text,
    created_at       timestamptz    not null default now(),
    constraint expense_transactions_type_check check (type in ('income', 'expense'))
);

create index if not exists idx_expense_transactions_school
    on expense_transactions (school_id);

create index if not exists idx_expense_transactions_school_date
    on expense_transactions (school_id, transaction_date desc, created_at desc);

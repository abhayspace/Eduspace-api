-- Priority order for savings allocation.

alter table expense_savings
    add column if not exists sort_order integer not null default 0;

create index if not exists idx_expense_savings_school_sort
    on expense_savings (school_id, sort_order asc, saved_date desc, created_at desc);

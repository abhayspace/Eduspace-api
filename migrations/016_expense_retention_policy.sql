-- Expense module retention policy (enforced in application code):
--   expense_savings        — no storage limit
--   expense_transactions   — rolling 1-year retention per school
--   expenses report        — aggregates all-time fees/payments/transactions (no cap)

comment on table expense_savings is 'Savings goals per school; no retention limit.';
comment on table expense_transactions is 'Manual income/expense entries; application retains 1 year per school.';

create index if not exists idx_expense_transactions_school_date_range
    on expense_transactions (school_id, transaction_date desc, created_at desc);

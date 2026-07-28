-- Extra fields for verified gateway payments / webhook audit.
alter table fee_payments
    add column if not exists currency text default 'INR';

alter table fee_payments
    add column if not exists event_payload jsonb not null default '{}'::jsonb;

alter table fee_payments
    add column if not exists verified_via text;

create index if not exists idx_fee_payments_order
    on fee_payments (school_id, gateway_order_id);

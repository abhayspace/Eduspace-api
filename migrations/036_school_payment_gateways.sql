-- Per-school payment gateway credentials (one active gateway per school).
create table if not exists school_payment_gateways (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid        not null references schools (id) on delete cascade,
    gateway_name    text        not null,
    merchant_name   text,
    merchant_id     text,
    key_id          text,
    key_secret      text,
    salt_key        text,
    salt_index      text,
    client_id       text,
    client_secret   text,
    webhook_secret  text,
    environment     text        not null default 'Sandbox'
                        check (environment in ('Sandbox', 'Production')),
    currency        text        not null default 'INR',
    active          boolean     not null default true,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);

create unique index if not exists uq_school_payment_gateways_active
    on school_payment_gateways (school_id)
    where active = true;

create index if not exists idx_school_payment_gateways_school
    on school_payment_gateways (school_id);

-- Gateway-backed fee payment ledger (receipts / orders / webhooks).
create table if not exists fee_payments (
    id                     uuid primary key default gen_random_uuid(),
    school_id              uuid           not null references schools (id) on delete cascade,
    student_id             uuid           references students (id) on delete set null,
    student_email          text,
    fee_id                 uuid           references fees (id) on delete set null,
    invoice_number         text,
    amount                 numeric(12, 2) not null default 0,
    tax                    numeric(12, 2) not null default 0,
    discount               numeric(12, 2) not null default 0,
    fine                   numeric(12, 2) not null default 0,
    total                  numeric(12, 2) not null default 0,
    gateway_name           text,
    gateway_order_id       text,
    gateway_payment_id     text,
    transaction_reference  text,
    payment_status         text           not null default 'created'
                               check (payment_status in (
                                   'created', 'pending', 'paid', 'failed', 'refunded', 'cancelled'
                               )),
    payment_method         text,
    payment_date           timestamptz,
    receipt_number         text,
    receipt_url            text,
    remarks                text,
    created_at             timestamptz    not null default now(),
    updated_at             timestamptz    not null default now()
);

create unique index if not exists uq_fee_payments_gateway_payment
    on fee_payments (school_id, gateway_name, gateway_payment_id)
    where gateway_payment_id is not null;

create unique index if not exists uq_fee_payments_gateway_order
    on fee_payments (school_id, gateway_name, gateway_order_id)
    where gateway_order_id is not null;

create index if not exists idx_fee_payments_school on fee_payments (school_id);
create index if not exists idx_fee_payments_student on fee_payments (school_id, student_id);
create index if not exists idx_fee_payments_status on fee_payments (school_id, payment_status);

-- Payment event audit log
create table if not exists payment_events (
    id           uuid primary key default gen_random_uuid(),
    school_id    uuid,
    gateway_name text,
    event_type   text        not null,
    payload      jsonb       not null default '{}'::jsonb,
    created_at   timestamptz not null default now()
);

create index if not exists idx_payment_events_school on payment_events (school_id);

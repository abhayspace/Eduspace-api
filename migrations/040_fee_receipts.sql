-- Fee receipt system: sequential numbers, PDF metadata, optional GST on schools.

alter table schools
    add column if not exists gst_number text;

create table if not exists fee_receipt_counters (
    school_id   uuid not null references schools (id) on delete cascade,
    year        integer not null,
    last_value  integer not null default 0,
    updated_at  timestamptz not null default now(),
    primary key (school_id, year)
);

create table if not exists fee_receipts (
    id              uuid primary key default gen_random_uuid(),
    receipt_number  text        not null,
    school_id       uuid        not null references schools (id) on delete cascade,
    student_id      uuid        references students (id) on delete set null,
    payment_id      uuid        not null references fee_payments (id) on delete cascade,
    invoice_number  text,
    pdf_path        text,
    pdf_url         text,
    snapshot        jsonb       not null default '{}'::jsonb,
    generated_at    timestamptz not null default now(),
    generated_by    text,
    created_at      timestamptz not null default now(),
    constraint uq_fee_receipts_number unique (receipt_number),
    constraint uq_fee_receipts_payment unique (payment_id)
);

create index if not exists idx_fee_receipts_school
    on fee_receipts (school_id);

create index if not exists idx_fee_receipts_student
    on fee_receipts (school_id, student_id);

create index if not exists idx_fee_receipts_generated
    on fee_receipts (school_id, generated_at desc);

create index if not exists idx_fee_receipts_number_search
    on fee_receipts (school_id, receipt_number);

-- Atomic next receipt sequence value for a school + calendar year.
create or replace function next_fee_receipt_seq(p_school_id uuid, p_year integer)
returns integer
language plpgsql
as $$
declare
    v_next integer;
begin
    insert into fee_receipt_counters (school_id, year, last_value, updated_at)
    values (p_school_id, p_year, 1, now())
    on conflict (school_id, year)
    do update set
        last_value = fee_receipt_counters.last_value + 1,
        updated_at = now()
    returning last_value into v_next;
    return v_next;
end;
$$;

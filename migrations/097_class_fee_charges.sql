-- Per-class custom fee charges (annual fee, caution money, etc.) applied in a chosen month.
create table if not exists class_fee_charges (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references schools(id) on delete cascade,
  class_id uuid not null references classes(id) on delete cascade,
  title text not null,
  amount numeric not null check (amount > 0),
  apply_month smallint not null check (apply_month between 1 and 12),
  created_at timestamptz not null default now()
);
create index if not exists class_fee_charges_school_idx on class_fee_charges (school_id);
create index if not exists class_fee_charges_month_idx on class_fee_charges (school_id, apply_month);

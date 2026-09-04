-- Subscription billing cycle, start/end dates, and plan_cancelled flag.
alter table schools add column if not exists billing_cycle text default 'monthly';
alter table schools add column if not exists subscription_start_date date;
alter table schools add column if not exists subscription_end_date date;
alter table schools add column if not exists plan_cancelled boolean not null default false;

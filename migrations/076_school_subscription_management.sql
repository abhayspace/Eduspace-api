-- Developer subscription management columns on schools table.
-- display_plan: plan shown on the admin's subscription page
-- actual_plan: plan that controls feature access
-- subscription_amount: amount (INR) the school needs to pay
-- payment_link: URL for payment; cleared by developer after payment confirmed
-- access_blocked: when true, non-admin users cannot login; admin sees non-skippable popup

alter table schools add column if not exists display_plan text;
alter table schools add column if not exists actual_plan text;
alter table schools add column if not exists subscription_amount numeric(12, 2) default 0;
alter table schools add column if not exists payment_link text;
alter table schools add column if not exists access_blocked boolean not null default false;

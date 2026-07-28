-- Allow "Other" environment for custom / future gateways.
alter table school_payment_gateways
    drop constraint if exists school_payment_gateways_environment_check;

alter table school_payment_gateways
    add constraint school_payment_gateways_environment_check
    check (environment in ('Sandbox', 'Production', 'Other'));

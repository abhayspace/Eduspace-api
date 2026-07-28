-- Homework: section + attachment fields; rolling 1-year retention (enforced in app).

alter table homework add column if not exists section_name text not null default '';
alter table homework add column if not exists attachment_url text;
alter table homework add column if not exists attachment_name text;

comment on table homework is 'Homework assignments; application retains 1 year per school.';

create index if not exists idx_homework_school_created_range
    on homework (school_id, created_at desc);

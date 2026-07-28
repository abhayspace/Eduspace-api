-- Announcements: rolling 1-year retention per school (enforced in application code).

comment on table announcements is 'School announcements; application retains 1 year per school.';

create index if not exists idx_announcements_school_created_range
    on announcements (school_id, created_at desc);

-- Leave requests: add "cancelled" status and 3-month retention policy.

-- Allow "cancelled" as a valid status.
alter table leave_requests
    drop constraint if exists leave_requests_status_check;

alter table leave_requests
    add constraint leave_requests_status_check
    check (status in ('pending', 'approved', 'rejected', 'cancelled'));

-- Purge leave requests older than 3 months (90 days).
-- This runs as part of the migration; a runtime purge also happens on list/create.
delete from leave_requests
where created_at < now() - interval '90 days';

-- Index for efficient retention purge.
create index if not exists idx_leave_requests_created_at
    on leave_requests (created_at);

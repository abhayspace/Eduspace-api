-- Leave requests: route student requests to their class teacher.
-- Teacher/staff requests continue to go to school admin.
--
-- reviewer_user_id stores the user_id of the designated reviewer:
--   - student requests → class teacher's user_id
--   - teacher/staff requests → NULL (any admin can review)
-- reviewer_role stores "class_teacher" or "admin" for clarity.

alter table leave_requests
    add column if not exists reviewer_user_id uuid references users (id) on delete set null,
    add column if not exists reviewer_role text not null default 'admin';

create index if not exists idx_leave_requests_reviewer
    on leave_requests (school_id, reviewer_role, reviewer_user_id);

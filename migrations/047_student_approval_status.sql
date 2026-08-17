-- Class-teacher student add requests require admin approval before the student is active/visible.
alter table students
  add column if not exists approval_status text not null default 'approved';

alter table students
  add column if not exists requested_by_user_id uuid references users (id) on delete set null;

alter table students
  drop constraint if exists students_approval_status_check;

alter table students
  add constraint students_approval_status_check
  check (approval_status in ('approved', 'pending', 'rejected'));

create index if not exists idx_students_approval_status
  on students (school_id, approval_status);

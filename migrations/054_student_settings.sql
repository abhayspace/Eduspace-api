-- Student module settings stored on the schools table.
-- class_teacher_can_add_student: whether class teachers can submit add-student requests (default true)
-- student_approval_required: whether school admin approval is needed before a student is active (default true)
alter table schools
  add column if not exists class_teacher_can_add_student boolean not null default true,
  add column if not exists student_approval_required boolean not null default true;

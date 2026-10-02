-- Parent-controlled flag: whether the linked student sees the Fees shortcut.
alter table users
  add column if not exists allow_student_fees_access boolean not null default true;

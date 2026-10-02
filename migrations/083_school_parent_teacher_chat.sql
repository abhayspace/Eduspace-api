-- Allow schools to toggle whether parents can start chats with teachers.
alter table schools
  add column if not exists allow_parent_teacher_chat boolean not null default false;

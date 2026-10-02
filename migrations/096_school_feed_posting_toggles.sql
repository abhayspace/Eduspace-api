-- Allow schools to control which roles can create School Feed posts.
alter table schools
  add column if not exists teacher_can_create_post boolean not null default true,
  add column if not exists student_can_create_post boolean not null default true;

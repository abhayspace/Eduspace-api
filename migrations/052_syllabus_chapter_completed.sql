-- Teachers tick off a chapter once it has been taught.

alter table syllabus_chapters add column if not exists completed boolean not null default false;
alter table syllabus_chapters add column if not exists completed_at timestamptz;

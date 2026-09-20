-- Parent profile fields on users (occupation + alternate contact).
alter table users add column if not exists occupation varchar;
alter table users add column if not exists alternate_mobile varchar;

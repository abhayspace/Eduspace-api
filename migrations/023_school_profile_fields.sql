-- Extra school fields captured during self-service registration.
alter table schools add column if not exists level_of_education varchar;
alter table schools add column if not exists total_students integer;
alter table schools add column if not exists total_teachers integer;

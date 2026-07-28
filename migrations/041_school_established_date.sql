-- School established date for profile editing.
alter table schools add column if not exists established_date date;

-- Whether the school runs classes on Sunday (default: closed).
alter table schools
  add column if not exists open_on_sunday boolean not null default false;

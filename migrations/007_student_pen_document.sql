-- Student PEN number and uploaded document metadata.

alter table students add column if not exists pen_number varchar(11);
alter table students add column if not exists document_url text;
alter table students add column if not exists document_name text;

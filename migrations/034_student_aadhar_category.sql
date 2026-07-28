-- Optional Aadhaar number + required category on student profiles.
alter table students add column if not exists aadhar_number varchar(12);
alter table students add column if not exists category text;

-- Backfill existing rows so category is always set for older profiles.
update students
set category = 'General'
where category is null or btrim(category) = '';

alter table students
  drop constraint if exists students_category_check;

alter table students
  add constraint students_category_check
  check (category in ('General', 'OBC', 'SC', 'ST', 'Minor'));

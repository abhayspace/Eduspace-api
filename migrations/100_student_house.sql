-- Optional "house" assignment for students (set by the class teacher / admin).
alter table students
    add column if not exists house text;

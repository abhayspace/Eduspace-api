-- Student login password (visible to school admin) and per-school admission numbers.

alter table users add column if not exists login_password text;

-- Per-school admission numbers (same number allowed across different schools).
do $$
begin
    if to_regclass('public.students') is not null then
        create unique index if not exists uq_students_school_admission_no
            on students (school_id, lower(trim(admission_no)))
            where admission_no is not null and trim(admission_no) <> '';
    end if;
end $$;

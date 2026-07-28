-- Day-specific substitute assignments for teacher free periods.

alter table teacher_substitute_assignments
    add column if not exists day_of_week text not null default 'monday';

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'teacher_substitute_assignments_day_of_week_check'
    ) then
        alter table teacher_substitute_assignments
            add constraint teacher_substitute_assignments_day_of_week_check
            check (day_of_week in (
                'monday',
                'tuesday',
                'wednesday',
                'thursday',
                'friday',
                'saturday',
                'sunday'
            ));
    end if;
end $$;

alter table teacher_substitute_assignments
    drop constraint if exists teacher_substitute_assignments_teacher_id_period_index_key;

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'teacher_substitute_assignments_teacher_period_day_key'
    ) then
        alter table teacher_substitute_assignments
            add constraint teacher_substitute_assignments_teacher_period_day_key
            unique (teacher_id, period_index, day_of_week);
    end if;
end $$;

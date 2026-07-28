-- Day-specific subject/teacher assignments for class-section schedules.

alter table class_section_period_assignments
    add column if not exists day_of_week text not null default 'monday';

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'class_section_period_assignments_day_of_week_check'
    ) then
        alter table class_section_period_assignments
            add constraint class_section_period_assignments_day_of_week_check
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

alter table class_section_period_assignments
    drop constraint if exists class_section_period_assignments_section_id_period_index_key;

-- Preserve existing one-schedule-for-all-days behavior by copying Monday rows
-- to the rest of the school week (only when those day rows are missing).
insert into class_section_period_assignments (
    school_id,
    class_id,
    section_id,
    period_index,
    subject_id,
    subject_name,
    teacher_id,
    teacher_name,
    updated_at,
    day_of_week
)
select
    src.school_id,
    src.class_id,
    src.section_id,
    src.period_index,
    src.subject_id,
    src.subject_name,
    src.teacher_id,
    src.teacher_name,
    src.updated_at,
    d.day_of_week
from class_section_period_assignments src
cross join (
    values
        ('tuesday'),
        ('wednesday'),
        ('thursday'),
        ('friday'),
        ('saturday')
) as d(day_of_week)
where src.day_of_week = 'monday'
  and not exists (
      select 1
      from class_section_period_assignments existing
      where existing.section_id = src.section_id
        and existing.period_index = src.period_index
        and existing.day_of_week = d.day_of_week
  );

do $$
begin
    if not exists (
        select 1
        from pg_constraint
        where conname = 'class_section_period_assignments_section_period_day_key'
    ) then
        alter table class_section_period_assignments
            add constraint class_section_period_assignments_section_period_day_key
            unique (section_id, period_index, day_of_week);
    end if;
end $$;

create index if not exists idx_class_section_period_assignments_section_day
    on class_section_period_assignments (section_id, day_of_week, period_index);

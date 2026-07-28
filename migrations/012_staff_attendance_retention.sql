-- Staff attendance: enforce status values and improve range queries.

alter table staff_attendance
    drop constraint if exists staff_attendance_status_check;

alter table staff_attendance
    add constraint staff_attendance_status_check
    check (status in ('present', 'absent', 'leave'));

create index if not exists idx_staff_attendance_school_date_desc
    on staff_attendance (school_id, date desc);

create index if not exists idx_staff_attendance_school_user_date
    on staff_attendance (school_id, user_id, date desc);

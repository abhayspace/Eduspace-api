-- School medical room visits: extends teacher_medical_visits with person_name and person_role
-- so the school admin can see who visited (teacher or student).

alter table teacher_medical_visits
    add column if not exists person_name text not null default '',
    add column if not exists person_role text not null default '';

create index if not exists idx_teacher_medical_visits_school_date
    on teacher_medical_visits (school_id, visit_date desc);

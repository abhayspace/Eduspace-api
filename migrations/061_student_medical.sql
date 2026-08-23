-- Student self-managed medical record (visible only to the student).
-- Mirrors the teacher medical columns (migration 049_teacher_medical.sql).

alter table students add column if not exists medical_height text;
alter table students add column if not exists medical_weight text;
alter table students add column if not exists medical_blood_group text;
alter table students add column if not exists medical_allergies text;
alter table students add column if not exists medical_conditions text;
alter table students add column if not exists medical_medications text;
alter table students add column if not exists medical_emergency_name text;
alter table students add column if not exists medical_emergency_relation text;
alter table students add column if not exists medical_emergency_mobile text;
alter table students add column if not exists medical_notes text;
alter table students add column if not exists medical_updated_at timestamptz;

-- Identification mark on the student medical record.
alter table students add column if not exists medical_identification_mark text;

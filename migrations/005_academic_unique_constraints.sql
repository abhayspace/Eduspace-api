-- Per-school unique class names and per-class unique section names.
-- Safe to re-run; index creation may fail if duplicate rows already exist for a school.

create unique index if not exists uq_classes_school_name_lower
    on classes (school_id, lower(trim(name)));

create unique index if not exists uq_sections_school_class_name_lower
    on sections (school_id, class_id, lower(trim(name)));

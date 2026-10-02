-- Optional itemized breakdown of a class/section monthly fee (e.g. tuition, smart class).
alter table class_section_fees
  add column if not exists breakdown jsonb;

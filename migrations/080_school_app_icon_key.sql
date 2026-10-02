-- Key of the app-icon bundled into the native build for this school
-- (premium white-label feature). When set together with use_school_logo,
-- the app switches its launcher icon/name to the school's bundled alias.
alter table schools
  add column if not exists app_icon_key text;

-- Administrator contact details collected at registration (no separate ADM login user).
alter table schools add column if not exists admin_email varchar;
alter table schools add column if not exists admin_mobile varchar;

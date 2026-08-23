-- Developer account for the EDUERP institution code.
-- This is a platform-level user (no school_id) that can view all schools
-- and their student/teacher/staff counts from the profile tab.
--
-- Default password: abha2011 (bcrypt hash below).
-- The password can be changed via the developer forgot-password flow
-- (OTP sent to abhaytri318@gmail.com) or the change-password endpoint.

insert into users (email, full_name, role, school_id, is_active, password_hash, login_password, user_code)
select
    'developer@eduspace.app',
    'Developer',
    'developer',
    null,
    true,
    '$2b$12$jTdNba7Veq60OE8Uqbg2/u09WIiP55sLgX.IEn0EmMdRGvywCBETq',
    'abha2011',
    'DEV001'
where not exists (
    select 1 from users where email = 'developer@eduspace.app'
);

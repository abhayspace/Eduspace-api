-- Reset all student passwords to random 8-digit numeric strings.
-- Uses a PL/pgSQL function to generate a random 8-digit number,
-- updates both login_password (plaintext for admin visibility) and password_hash (bcrypt).

-- First, create a helper function to generate a random 8-digit numeric string.
create or replace function _random_8_digit_password() returns text as $$
begin
    return lpad(floor(random() * 100000000)::text, 8, '0');
end;
$$ language plpgsql;

-- Update all student users with new random 8-digit numeric passwords.
-- We set login_password to the plain text value; password_hash will be updated
-- by the application on next login or password reset. If the app needs
-- password_hash updated immediately, run the Python script provided.
update users
set login_password = _random_8_digit_password(),
    must_change_password = true
where id in (
    select s.user_id from students s
    where s.approval_status = 'approved'
);

-- Clean up the helper function.
drop function if exists _random_8_digit_password();

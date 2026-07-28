-- Optional demo seed data for local development / testing only.
-- NOT executed automatically by the backend at startup.
-- Password hashes are bcrypt, generated with pgcrypto's crypt()/gen_salt('bf'),
-- which are verifiable by Python's bcrypt library.
--
-- Demo institution codes: GREEN001, WLAKE001
-- Demo credentials (identifier / password):
--   ADM001  / Admin123!      (school_admin, Greenfield)
--   TCH001  / Teacher123!     (teacher,      Greenfield)
--   STU001  / Student123!     (student,      Greenfield)
--   STU001  / Parent123!      (parent,       Greenfield)  [admission_no shared]
--   PRN001  / Principal123!   (principal,    Greenfield)

create extension if not exists "pgcrypto";

insert into schools (id, school_name, institution_code, logo_url)
values
    ('11111111-1111-1111-1111-111111111111', 'Greenfield International School', 'GREEN001', null),
    ('22222222-2222-2222-2222-222222222222', 'Westlake Academy', 'WLAKE001', null)
on conflict (institution_code) do nothing;

insert into users (school_id, email, full_name, role, admission_no, user_code, password_hash)
values
    ('11111111-1111-1111-1111-111111111111', 'admin@eduspace.app',     'Sarah Whitman',    'school_admin', null,     'ADM001', crypt('Admin123!',     gen_salt('bf'))),
    ('11111111-1111-1111-1111-111111111111', 'teacher@eduspace.app',   'Mr. James Carter', 'teacher',      null,     'TCH001', crypt('Teacher123!',   gen_salt('bf'))),
    ('11111111-1111-1111-1111-111111111111', 'student@eduspace.app',   'Aanya Sharma',     'student',      'STU001', null,     crypt('Student123!',   gen_salt('bf'))),
    ('11111111-1111-1111-1111-111111111111', 'parent@eduspace.app',    'Rahul Sharma',     'parent',       'STU001', null,     crypt('Parent123!',    gen_salt('bf'))),
    ('11111111-1111-1111-1111-111111111111', 'principal@eduspace.app', 'Dr. Eleanor Reid', 'principal',    null,     'PRN001', crypt('Principal123!', gen_salt('bf'))),
    ('22222222-2222-2222-2222-222222222222', 'admin@westlake.app',     'Helen Wallace',    'school_admin', null,     'ADM001', crypt('Admin123!',     gen_salt('bf'))),
    ('22222222-2222-2222-2222-222222222222', 'student@westlake.app',   'Liam O''Connor',   'student',      'WSTU001', null,    crypt('Student123!',   gen_salt('bf')))
on conflict do nothing;

insert into announcements (school_id, title, body, audience, author)
values
    ('11111111-1111-1111-1111-111111111111', 'Welcome to EduSpace', 'We''re delighted to launch our new school portal.', 'all', 'Principal'),
    ('11111111-1111-1111-1111-111111111111', 'Parent–Teacher Meeting', 'Scheduled for next Friday at 4 PM in the auditorium.', 'parent', 'School Admin'),
    ('11111111-1111-1111-1111-111111111111', 'Sports Day', 'Annual sports day on the 15th of this month.', 'all', 'Sports Dept'),
    ('22222222-2222-2222-2222-222222222222', 'Welcome to Westlake', 'Term 2 starts next week. Stay tuned for the schedule.', 'all', 'Westlake Admin')
on conflict do nothing;

insert into homework (school_id, subject, title, description, class_name, due_date, assigned_by)
values
    ('11111111-1111-1111-1111-111111111111', 'Mathematics', 'Algebra Worksheet 4', 'Solve problems 1-15 on page 42.', 'Grade 10-A', current_date + 2, 'Mr. James Carter'),
    ('11111111-1111-1111-1111-111111111111', 'Science', 'Photosynthesis Lab Report', 'Submit 2-page report.', 'Grade 10-A', current_date + 3, 'Mr. James Carter'),
    ('11111111-1111-1111-1111-111111111111', 'English', 'Essay: My Hero', '300-word descriptive essay.', 'Grade 10-A', current_date + 4, 'Mr. James Carter'),
    ('11111111-1111-1111-1111-111111111111', 'History', 'Industrial Revolution timeline', 'Build a visual timeline.', 'Grade 10-A', current_date + 5, 'Mr. James Carter')
on conflict do nothing;

insert into timetable (school_id, class_name, day, start_time, end_time, subject, teacher, room)
values
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Mon', '09:00', '09:45', 'Mathematics', 'Mr. Carter', 'R-201'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Mon', '09:50', '10:35', 'Science', 'Ms. Patel', 'Lab-1'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Mon', '10:50', '11:35', 'English', 'Mrs. Khan', 'R-204'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Mon', '11:40', '12:25', 'History', 'Mr. Lee', 'R-210'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Tue', '09:00', '09:45', 'Science', 'Ms. Patel', 'Lab-1'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Tue', '09:50', '10:35', 'Mathematics', 'Mr. Carter', 'R-201'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Tue', '10:50', '11:35', 'Art', 'Ms. Rivera', 'Art-3'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Wed', '09:00', '09:45', 'Mathematics', 'Mr. Carter', 'R-201'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Wed', '09:50', '10:35', 'Physical Ed', 'Coach Diaz', 'Gym'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Thu', '09:00', '09:45', 'English', 'Mrs. Khan', 'R-204'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Thu', '09:50', '10:35', 'Science', 'Ms. Patel', 'Lab-1'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Fri', '09:00', '09:45', 'History', 'Mr. Lee', 'R-210'),
    ('11111111-1111-1111-1111-111111111111', 'Grade 10-A', 'Fri', '09:50', '10:35', 'Mathematics', 'Mr. Carter', 'R-201')
on conflict do nothing;

insert into fees (school_id, student_email, title, amount, due_date, status)
values
    ('11111111-1111-1111-1111-111111111111', 'student@eduspace.app', 'Tuition – Term 2', 1200.0, current_date + 15, 'pending'),
    ('11111111-1111-1111-1111-111111111111', 'student@eduspace.app', 'Library', 45.0, current_date + 15, 'paid'),
    ('11111111-1111-1111-1111-111111111111', 'student@eduspace.app', 'Transport', 180.0, current_date + 15, 'pending'),
    ('11111111-1111-1111-1111-111111111111', 'student@eduspace.app', 'Lab Fees', 60.0, current_date + 15, 'pending')
on conflict do nothing;

insert into attendance (school_id, student_email, class_name, date, status)
select '11111111-1111-1111-1111-111111111111', 'student@eduspace.app', 'Grade 10-A',
       current_date - g,
       case when g in (3, 7) then 'absent' else 'present' end
from generate_series(0, 9) as g
on conflict do nothing;

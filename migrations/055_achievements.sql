-- Achievements module migration
-- Main achievements table
create table if not exists achievements (
  id uuid primary key default gen_random_uuid(),
  school_id uuid not null references schools(id) on delete cascade,
  title text not null,
  description text not null,
  type text not null check (type in ('school', 'student', 'teacher')),
  category text check (category in ('academic', 'sports', 'cultural', 'competition', 'olympiad', 'event', 'attendance', 'other')),
  level text check (level in ('school', 'district', 'state', 'national', 'international')),
  achievement_date date,
  cover_image text,
  created_by uuid not null references users(id),
  created_at timestamp with time zone default now(),
  updated_at timestamp with time zone default now()
);

-- Achievement images gallery
create table if not exists achievement_images (
  id uuid primary key default gen_random_uuid(),
  achievement_id uuid not null references achievements(id) on delete cascade,
  image_url text not null,
  created_at timestamp with time zone default now()
);

-- Achievement attachments (certificates)
create table if not exists achievement_attachments (
  id uuid primary key default gen_random_uuid(),
  achievement_id uuid not null references achievements(id) on delete cascade,
  file_url text not null,
  file_name text,
  file_type text check (file_type in ('pdf', 'image')),
  created_at timestamp with time zone default now()
);

-- Achievement assignments (for student/teacher achievements)
create table if not exists achievement_assignments (
  id uuid primary key default gen_random_uuid(),
  achievement_id uuid not null references achievements(id) on delete cascade,
  user_type text not null check (user_type in ('student', 'teacher')),
  user_id uuid not null,
  created_at timestamp with time zone default now(),
  unique(achievement_id, user_type, user_id)
);

-- Indexes for performance
create index if not exists idx_achievements_school_id on achievements(school_id);
create index if not exists idx_achievements_type on achievements(type);
create index if not exists idx_achievements_category on achievements(category);
create index if not exists idx_achievements_achievement_date on achievements(achievement_date);
create index if not exists idx_achievements_created_at on achievements(created_at desc);

create index if not exists idx_achievement_images_achievement_id on achievement_images(achievement_id);
create index if not exists idx_achievement_attachments_achievement_id on achievement_attachments(achievement_id);
create index if not exists idx_achievement_assignments_achievement_id on achievement_assignments(achievement_id);
create index if not exists idx_achievement_assignments_user_id on achievement_assignments(user_id);
create index if not exists idx_achievement_assignments_user_type on achievement_assignments(user_type);

-- Updated at trigger
drop trigger if exists trigger_achievements_updated_at on achievements;

create or replace function update_achievements_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trigger_achievements_updated_at
  before update on achievements
  for each row
  execute function update_achievements_updated_at();

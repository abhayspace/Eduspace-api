-- Add pinned column to achievements
alter table achievements add column if not exists pinned boolean not null default false;

-- Index for quick lookup of pinned achievements
create index if not exists idx_achievements_pinned on achievements(pinned);

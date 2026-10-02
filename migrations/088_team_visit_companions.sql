-- Companions on team visits — other team members going along.

alter table team_visits
    add column if not exists companions text not null default '';

-- Documents field for team members (developer-managed, shown on the member's
-- dashboard "Documents" card).

alter table team_members
    add column if not exists documents text not null default '';

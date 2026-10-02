-- Shared team documents — admin uploads files, every member can see/download.

create table if not exists team_documents (
    id          uuid primary key default gen_random_uuid(),
    file_name   varchar     not null default '',
    stored_name varchar     not null default '',
    size_bytes  bigint      not null default 0,
    uploaded_by varchar     not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists team_documents_created_idx
    on team_documents (created_at desc);

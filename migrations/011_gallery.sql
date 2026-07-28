-- Gallery folders and media (scoped per school)

create table if not exists gallery_folders (
    id          uuid        primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    name        text        not null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);

create index if not exists idx_gallery_folders_school on gallery_folders (school_id);

create table if not exists gallery_media (
    id           uuid        primary key default gen_random_uuid(),
    school_id    uuid        not null references schools (id) on delete cascade,
    folder_id    uuid        not null references gallery_folders (id) on delete cascade,
    media_type   text        not null check (media_type in ('image', 'video')),
    file_url     text        not null,
    file_name    text        not null,
    content_type text        not null,
    created_at   timestamptz not null default now()
);

create index if not exists idx_gallery_media_school on gallery_media (school_id);
create index if not exists idx_gallery_media_folder on gallery_media (folder_id);

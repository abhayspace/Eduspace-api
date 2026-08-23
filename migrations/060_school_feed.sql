-- School Feed: posts (photo(s) + caption) shared by any user in the school,
-- with likes and comments.

create table if not exists feed_posts (
    id             uuid        primary key default gen_random_uuid(),
    school_id      uuid        not null references schools (id) on delete cascade,
    author_id      uuid        not null references users (id) on delete cascade,
    author_name    text        not null default '',
    author_role    text        not null default '',
    caption        text        not null default '',
    created_at     timestamptz not null default now()
);

create index if not exists idx_feed_posts_school on feed_posts (school_id, created_at desc);
create index if not exists idx_feed_posts_author on feed_posts (author_id);

create table if not exists feed_post_media (
    id           uuid        primary key default gen_random_uuid(),
    post_id      uuid        not null references feed_posts (id) on delete cascade,
    school_id    uuid        not null references schools (id) on delete cascade,
    file_url     text        not null,
    file_name    text        not null default '',
    content_type text        not null default 'image/jpeg',
    position     int         not null default 0,
    created_at   timestamptz not null default now()
);

create index if not exists idx_feed_post_media_post on feed_post_media (post_id, position);

create table if not exists feed_likes (
    id         uuid        primary key default gen_random_uuid(),
    post_id    uuid        not null references feed_posts (id) on delete cascade,
    user_id    uuid        not null references users (id) on delete cascade,
    created_at timestamptz not null default now(),
    unique (post_id, user_id)
);

create index if not exists idx_feed_likes_post on feed_likes (post_id);

create table if not exists feed_comments (
    id          uuid        primary key default gen_random_uuid(),
    post_id     uuid        not null references feed_posts (id) on delete cascade,
    school_id   uuid        not null references schools (id) on delete cascade,
    user_id     uuid        not null references users (id) on delete cascade,
    author_name text        not null default '',
    text        text        not null,
    created_at  timestamptz not null default now()
);

create index if not exists idx_feed_comments_post on feed_comments (post_id, created_at);

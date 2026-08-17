create table if not exists library_books (
    id                          uuid primary key default gen_random_uuid(),
    school_id                   uuid        not null references schools (id) on delete cascade,
    title                       text        not null,
    author                      text        not null default '',
    subject                     text        not null default '',
    category                    text        not null default '',
    isbn                        text        not null default '',
    publisher                   text        not null default '',
    edition                     text        not null default '',
    language                    text        not null default '',
    shelf_number                text        not null default '',
    cover_image_url             text,
    description                 text        not null default '',
    total_copies                integer     not null default 1 check (total_copies >= 0),
    is_digital                  boolean     not null default false,
    digital_resource_url        text,
    digital_resource_format     text        not null default '',
    popularity_score            integer     not null default 0,
    is_active                   boolean     not null default true,
    created_at                  timestamptz not null default now(),
    updated_at                  timestamptz not null default now()
);
create index if not exists idx_library_books_school on library_books (school_id);
create index if not exists idx_library_books_category on library_books (school_id, category);
create index if not exists idx_library_books_subject on library_books (school_id, subject);
create index if not exists idx_library_books_created on library_books (school_id, created_at desc);

create table if not exists library_issues (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    book_id             uuid        not null references library_books (id) on delete cascade,
    issued_to_user_id   uuid        not null references users (id) on delete cascade,
    issue_date          date        not null,
    due_date            date        not null,
    return_date         date,
    renewed_count       integer     not null default 0 check (renewed_count >= 0),
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_library_issues_school on library_issues (school_id);
create index if not exists idx_library_issues_user on library_issues (school_id, issued_to_user_id);
create index if not exists idx_library_issues_book on library_issues (school_id, book_id);
create index if not exists idx_library_issues_due on library_issues (school_id, due_date);

create table if not exists library_requests (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid        not null references schools (id) on delete cascade,
    book_id             uuid        not null references library_books (id) on delete cascade,
    requester_user_id   uuid        not null references users (id) on delete cascade,
    issue_id            uuid        references library_issues (id) on delete set null,
    request_type        text        not null default 'book'
        check (request_type in ('book', 'renewal')),
    status              text        not null default 'pending_approval'
        check (status in ('pending_approval', 'approved', 'ready_for_pickup', 'rejected', 'cancelled')),
    note                text        not null default '',
    requested_at        timestamptz not null default now(),
    decided_at          timestamptz,
    cancelled_at        timestamptz
);
create index if not exists idx_library_requests_school on library_requests (school_id);
create index if not exists idx_library_requests_user on library_requests (school_id, requester_user_id);
create index if not exists idx_library_requests_book on library_requests (school_id, book_id);
create index if not exists idx_library_requests_issue on library_requests (school_id, issue_id);
create index if not exists idx_library_requests_status on library_requests (school_id, status);

create table if not exists library_favorites (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid        not null references schools (id) on delete cascade,
    user_id     uuid        not null references users (id) on delete cascade,
    book_id     uuid        not null references library_books (id) on delete cascade,
    created_at  timestamptz not null default now(),
    unique (school_id, user_id, book_id)
);
create index if not exists idx_library_favorites_school on library_favorites (school_id);
create index if not exists idx_library_favorites_user on library_favorites (school_id, user_id);
create index if not exists idx_library_favorites_book on library_favorites (school_id, book_id);

# Backend Performance Audit Report — EduSpace API

## Architecture Context

The EduSpace backend uses **Supabase's PostgREST HTTP API** (via the `supabase-py` async client) for all database operations. Every `client.table("x").select().execute()` call is a **full HTTP round trip** to the Supabase PostgREST endpoint, not a direct PostgreSQL query.

Each "query" includes:
1. HTTP request serialization
2. Network latency (VPS → Supabase, ~4ms baseline)
3. PostgREST query parsing & SQL execution
4. HTTP response serialization
5. JSON parsing in Python

**Key insight**: Even with 4ms latency, 100 sequential queries = 400ms. The number of HTTP round trips per request is the dominant performance factor.

---

## Bottlenecks Found & Fixed

### 1. N+1 Queries in `list_students` (CRITICAL — fixed in prior session)

**File**: `services/student_service.py` — `list_students()`
- **Before**: 1 query for students + 1 for users + **2 queries per student** (class name + section name) = up to **1,003 HTTP round trips** for 500 students
- **After**: Batched class/section lookups with `in_()` = **5 queries total**
- **Impact**: ~99.5% reduction in DB round trips

### 2. N+1 Queries in `list_teachers` (CRITICAL — fixed in prior session)

**File**: `services/teacher_service.py` — `list_teachers()`
- **Before**: Same pattern — up to **1,003 HTTP round trips** for 500 teachers
- **After**: Batched lookups = **5 queries total**
- **Impact**: ~99.5% reduction in DB round trips

### 3. `/stats` Endpoint — Sequential Queries After `asyncio.gather` (HIGH)

**File**: `routers/misc.py` — `stats()`
- **Before**: 7 queries in `asyncio.gather` + **3 sequential queries** (teacher count, parent count, homework count) after the gather completed. Also, `_attendance_pct_today` internally called `_count_students`/`_count_staff` again (duplicate count queries).
- **After**: All 10 queries run in a single `asyncio.gather` (2-phase: fetch counts first, then pass them to attendance pct). Eliminates 5 redundant queries.
- **Impact**: ~50% faster — from ~13 sequential queries to 2 parallel batches

### 4. `_expenses_report` — 3 Sequential Queries Loading All Rows (HIGH)

**File**: `routers/misc.py` — `_expenses_report()`
- **Before**: 3 sequential queries (`payments`, `fees`, `expense_transactions`) with **no date filters** — loaded ALL rows from each table, then filtered in Python
- **After**: 3 queries in `asyncio.gather` with **date range filters** added to `payments` and `expense_transactions` queries. Fees table still fetches all (needed for paid/pending status filtering).
- **Impact**: ~3x faster + dramatically reduced payload size for schools with many payment records

### 5. Purge-on-Every-Request Anti-Pattern (HIGH)

Multiple services ran expensive DELETE queries on **every single list request**:

| Service | Function | TTL Applied |
|---|---|---|
| `announcement_service.py` | `purge_expired_announcements()` | 300s (5 min) |
| `homework_service.py` | `purge_expired_homework()` | 300s (5 min) |
| `expense_service.py` | `_purge_expired_transactions()` | 300s (5 min) |
| `fee_structure_service.py` | `purge_old_paid_fees()` | 600s (10 min) |
| `fee_structure_service.py` | `ensure_current_month_fees()` | 600s (10 min) |

- **Before**: Each list endpoint (announcements, homework, transactions, fees) executed 1-3 DELETE queries + SELECT queries on every request, even if no data had changed
- **After**: Throttled via `utils/ttl_cache.py` — purge runs at most once per 5-10 minutes per school
- **Impact**: Eliminates 2-4 unnecessary HTTP round trips per list request for all subsequent requests within the TTL window

### 6. `ensure_defaults` on Every Academic List Request (HIGH)

**File**: `services/academic_service.py` — `ensure_defaults()`
- **Before**: `list_classes()`, `list_sections()`, `list_subjects()`, `create_class()` all called `ensure_defaults()`, which ran a SELECT + potential INSERT on every request
- **After**: Throttled to once per 60 seconds per school
- **Impact**: Eliminates 1-2 HTTP round trips per academic list request

### 7. N+1 in `_apply_monthly_fees_for_sections` (HIGH)

**File**: `services/fee_structure_service.py` — `_apply_monthly_fees_for_sections()`
- **Before**: For each student email in each section, executed a separate SELECT to check if a fee already exists, then a separate INSERT if not. For 100 students across 5 sections = **100+ sequential queries**.
- **After**: Single batched SELECT with `in_("student_email", all_emails)` + single batched INSERT for all new fees
- **Impact**: ~100 queries → 2-3 queries regardless of student count

### 8. Calendar `list_month` — Loading All Events (MEDIUM)

**File**: `services/calendar_service.py` — `list_month()`
- **Before**: Fetched ALL school calendar events (no date filter), then filtered in Python
- **After**: Added `.lte("event_date", month_end)` and `.gte("end_date", month_start)` to query — only events overlapping the requested month are fetched
- **Impact**: Reduced payload from all-events to just current-month events

### 9. Calendar `_profile_birthdays` — Sequential Table Scans (MEDIUM)

**File**: `services/calendar_service.py` — `_profile_birthdays()`
- **Before**: Fetched students, teachers, and staff_profiles **sequentially**, then queried users separately for each table
- **After**: All 3 table queries run in `asyncio.gather`, then a single batched users query for all user_ids
- **Impact**: 6 sequential queries → 2 parallel batches (4 queries total)

### 10. `_folder_name_taken` — Fetch-All-And-Filter (MEDIUM)

**File**: `services/gallery_service.py` — `_folder_name_taken()`
- **Before**: Fetched ALL gallery folders for the school, then iterated in Python to check name collision
- **After**: Targeted `.ilike("name", name.strip()).limit(1)` query — returns at most 1 row
- **Impact**: Dramatically reduced payload for schools with many folders

### 11. `school_fee_dashboard_stats` — Fetching All Fees Instead of Pending Only (MEDIUM)

**File**: `services/fee_structure_service.py` — `school_fee_dashboard_stats()`
- **Before**: Paginated through ALL fees (paid + pending) to compute pending_total and unpaid_emails, then separately paginated through payments
- **After**: Only fetches pending fees (`.eq("status", "pending")`), reducing payload significantly. Pending fees and payments queries run in parallel.
- **Impact**: Reduced per-page payload from all-fees to pending-only; parallel execution

### 12. Sequential Queries in Library Service (MEDIUM)

**File**: `services/library_service.py`
- `get_summary()`: 4 sequential count queries → all in `asyncio.gather`
- `get_school_stats()`: 3 sequential count queries → all in `asyncio.gather`
- `list_books()`: issue_stats and favorites queries were sequential → now in `asyncio.gather`
- **Impact**: 3-4 sequential queries → 1 parallel batch each

### 13. Sequential Queries in Gallery & Expense Services (MEDIUM)

**File**: `services/gallery_service.py` — `list_folders()`
- Folders and media queries sequential → now in `asyncio.gather`

**File**: `services/expense_service.py` — `_list_transactions_merged()`
- Expense transactions and payments queries sequential → now in `asyncio.gather`

### 14. `_find_class_by_name` — Fetch-All-And-Filter (LOW)

**File**: `services/academic_service.py` — `_find_class_by_name()`
- **Before**: Fetched ALL classes for the school, then did case-insensitive name matching in Python
- **After**: Uses `.ilike("name", name.strip()).limit(1)` — single targeted query
- **Impact**: Reduced payload from all-classes to 1 row

### 15. `list_fee_structure` — Sequential Classes + Fees Queries (LOW)

**File**: `services/fee_structure_service.py` — `list_fee_structure()`
- **Before**: Fetched classes, then fees sequentially
- **After**: Both queries in `asyncio.gather`
- **Impact**: 2 sequential → 1 parallel batch

---

## Profiling Infrastructure (from prior session)

### `middleware/profiling.py`
- Logs total request time, DB time, processing time, and query count for every `/api/` request
- Flags slow queries (>200ms) and slow requests (>500ms)
- Adds `X-Total-Time-ms`, `X-DB-Time-ms`, `X-Query-Count` response headers

### `database.py` — `TimedClient` / `TimedQueryBuilder`
- Wraps every `.execute()` call with timing via contextvars
- Zero code changes needed in service layer — timing is transparent

---

## Summary of Changes

| # | File | Function | Issue | Fix | Queries Before | Queries After |
|---|---|---|---|---|---|---|
| 1 | `student_service.py` | `list_students` | N+1 class/section | Batch `in_()` | ~1003 | 5 |
| 2 | `teacher_service.py` | `list_teachers` | N+1 class/section | Batch `in_()` | ~1003 | 5 |
| 3 | `routers/misc.py` | `stats` | Sequential + duplicate counts | `asyncio.gather` + pass totals | ~13 | 10 (parallel) |
| 4 | `routers/misc.py` | `_expenses_report` | Sequential, no date filter | `asyncio.gather` + date filters | 3 (all rows) | 3 (filtered, parallel) |
| 5 | 5 service files | 5 purge functions | DELETE on every request | TTL throttle (5-10 min) | 2-4/request | 0 (cached) |
| 6 | `academic_service.py` | `ensure_defaults` | SELECT on every request | TTL throttle (60s) | 1-2/request | 0 (cached) |
| 7 | `fee_structure_service.py` | `_apply_monthly_fees_for_sections` | N+1 per student | Batch SELECT + INSERT | ~100+ | 2-3 |
| 8 | `calendar_service.py` | `list_month` | Load all events | Date range filter | 1 (all events) | 1 (month only) |
| 9 | `calendar_service.py` | `_profile_birthdays` | Sequential table scans | `asyncio.gather` + batch users | 6 | 4 (parallel) |
| 10 | `gallery_service.py` | `_folder_name_taken` | Fetch all folders | `.ilike().limit(1)` | 1 (all) | 1 (1 row) |
| 11 | `fee_structure_service.py` | `school_fee_dashboard_stats` | Fetch all fees | Filter pending only + parallel | 2+ (all fees) | 2 (pending only, parallel) |
| 12 | `library_service.py` | 3 functions | Sequential count queries | `asyncio.gather` | 3-4 each | 1 batch each |
| 13 | `gallery_service.py` | `list_folders` | Sequential queries | `asyncio.gather` | 2 | 1 (parallel) |
| 14 | `expense_service.py` | `_list_transactions_merged` | Sequential queries | `asyncio.gather` | 2 | 1 (parallel) |
| 15 | `academic_service.py` | `_find_class_by_name` | Fetch all + Python filter | `.ilike().limit(1)` | 1 (all) | 1 (1 row) |
| 16 | `fee_structure_service.py` | `list_fee_structure` | Sequential queries | `asyncio.gather` | 2 | 1 (parallel) |

---

## New Files Created

- **`utils/ttl_cache.py`** — Simple in-memory TTL cache for throttling recurring operations. Uses `time.monotonic()` and a dict of timestamps.

---

## Expected Overall Performance Impact

| Endpoint | Before (queries) | After (queries) | Improvement |
|---|---|---|---|
| `GET /api/students` (500) | ~1003 | 5 | **~200x fewer DB calls** |
| `GET /api/teachers` (500) | ~1003 | 5 | **~200x fewer DB calls** |
| `GET /api/stats` | ~13 sequential | 10 parallel (2 batches) | **~3x faster** |
| `GET /api/stats/expenses-report` | 3 sequential (all rows) | 3 parallel (filtered) | **~3x faster + smaller payload** |
| `GET /api/announcements` | 2-3 (incl. purge) | 1 (purge cached) | **~2-3x faster** |
| `GET /api/homework` | 3-4 (incl. purge) | 1 (purge cached) | **~3-4x faster** |
| `GET /api/expenses` | 3-4 (incl. purge) | 2 parallel (purge cached) | **~2-3x faster** |
| `GET /api/fee-structure` | 5-10+ (incl. ensure+purge) | 2 parallel (cached) | **~5x faster** |
| `GET /api/calendar/month` | 5-6 (all events) | 3-4 (filtered, parallel) | **~2x faster** |
| `GET /api/gallery/folders` | 2 sequential | 2 parallel | **~2x faster** |
| `GET /api/library/summary` | 5 sequential | 1 parallel batch + 1 | **~3x faster** |
| `GET /api/library/books` | 3 sequential | 2 parallel | **~1.5x faster** |

---

## Recommendations (Not Yet Implemented)

1. **Short-lived user cache for auth middleware** — `utils/deps.py:get_user_by_token()` runs 1 query per authenticated request. A 30-second TTL cache keyed by user_id would eliminate this for rapid successive requests.

2. **Direct PostgreSQL connection for hot paths** — If the VPS has direct PostgreSQL access (`DATABASE_URL`), switching to `asyncpg` for list endpoints would eliminate HTTP overhead entirely (~5-10x faster per query).

3. **PostgREST count optimization** — The `_count()` helper uses `head=True` with `count="exact"`, which requires PostgREST to do a full count query. For large tables, this can be slow. Consider approximate counts or cached counts for dashboard stats.

4. **Pagination for list endpoints** — Several list endpoints use `.limit(500)` but don't support cursor-based pagination. For schools with >500 records, this silently truncates data. Consider adding `offset`/`cursor` parameters.

5. **Supabase connection pooling** — The `supabase-py` async client creates HTTP connections per request. Configuring HTTP keep-alive or connection pooling at the HTTP client level would reduce connection overhead.

# Backend Profiling Report — EduSpace API

## Architecture Context

The EduSpace backend uses **Supabase's PostgREST HTTP API** (via the `supabase-py` async client) for all database operations. This means every `client.table("x").select().execute()` call is **not a direct PostgreSQL query** — it's a full HTTP round trip to the Supabase PostgREST endpoint.

This is the single biggest performance factor: each "query" includes:
1. HTTP request serialization
2. Network latency (VPS → Supabase)
3. PostgREST query parsing & SQL execution
4. HTTP response serialization
5. JSON parsing in Python

## Bottlenecks Found

### 1. N+1 Queries in List Endpoints (CRITICAL)

**`list_students`** (`services/student_service.py`):
- **Before**: For N students, executed `2 + 1 + (N × 2)` queries = up to **1,003 HTTP round trips** for 500 students
  - 1 query for students
  - 1 query for users (batched with `in_()`)
  - N queries for class names (one per student via `_resolve_class_section`)
  - N queries for section names (one per student)
- **After**: Fixed to `2 + 1 + 2` = **5 queries total** (batched class/section lookups with `in_()`)
- **Impact**: ~99.5% reduction in DB round trips for student list

**`list_teachers`** (`services/teacher_service.py`):
- **Before**: Same pattern — up to **1,003 HTTP round trips** for 500 teachers
- **After**: Fixed to **5 queries total**
- **Impact**: ~99.5% reduction in DB round trips for teacher list

### 2. Per-Request Auth Query (MODERATE)

Every authenticated request executes 1 query to fetch the user by JWT `sub` claim (`utils/deps.py:24-30`). This is unavoidable without caching but adds 1 HTTP round trip per request.

**Potential optimization**: Short-lived in-memory cache (e.g., 30-second TTL) for user objects keyed by user_id. Would eliminate this query for rapid successive requests from the same user.

### 3. PostgREST HTTP Overhead (ARCHITECTURAL)

Each Supabase query is an HTTP call. With Supabase hosted separately from the VPS:
- **Network latency**: 20-100ms per query depending on Supabase region vs VPS location
- **No connection pooling**: Each query opens a new HTTP connection
- **No prepared statements**: PostgREST parses SQL fresh each time

**Potential optimization**: If the VPS has direct PostgreSQL access (`DATABASE_URL`), switching to `asyncpg` for hot paths would eliminate HTTP overhead entirely (~5-10x faster per query).

## Changes Made

### Profiling Infrastructure

1. **`middleware/profiling.py`** — New request profiling middleware:
   - Logs total request time, DB time, processing time, and query count for every `/api/` request
   - Flags slow queries (>200ms) and slow requests (>500ms)
   - Adds `X-Total-Time-ms`, `X-DB-Time-ms`, `X-Query-Count` response headers

2. **`database.py`** — Wrapped Supabase client with `TimedClient` / `TimedQueryBuilder`:
   - Every `.execute()` call is timed and recorded via contextvars
   - Slow queries (>200ms) logged with table name
   - Zero code changes needed in service layer — timing is transparent

3. **`main.py`** — Registered `ProfilingMiddleware`

### N+1 Query Fixes

4. **`services/student_service.py`** — `list_students()`:
   - Replaced per-student `_resolve_class_section()` calls with batched `in_()` lookups
   - Collects unique class_ids and section_ids, fetches in 2 queries

5. **`services/teacher_service.py`** — `list_teachers()`:
   - Same batch optimization for class teacher class/section name resolution

### Migration Fix

6. **`migrate.py`** — Added missing `055_leave_requests_cancel_and_retention.sql` to migration order

## Expected Performance Impact

| Endpoint | Before | After | Improvement |
|---|---|---|---|
| `GET /api/students` (500 students) | ~1003 queries | ~5 queries | **~200x fewer DB calls** |
| `GET /api/teachers` (500 teachers) | ~1003 queries | ~5 queries | **~200x fewer DB calls** |
| All other endpoints | No profiling | Full timing logs | **Visibility** |

## Log Output Format

Every API request now logs:
```
INFO eduspace.profiling: GET /api/students | total=340ms | db=310ms | proc=30ms | queries=5
```

Slow requests (>500ms):
```
INFO eduspace.profiling: SLOW: GET /api/students | total=1200ms | db=1100ms | proc=100ms | queries=5
```

Very slow requests (>1s):
```
WARNING eduspace.profiling: SLOW REQUEST: GET /api/students | total=2500ms | db=2400ms | proc=100ms | queries=5
```

Slow queries (>200ms):
```
WARNING eduspace.database: SLOW QUERY students: 350ms
```

## Recommendations

1. **Run migrations** on the new VPS database (`python migrate.py`) — missing columns cause 500 errors
2. **Check Supabase region** — ensure it's geographically close to the Contabo VPS to minimize HTTP latency
3. **Consider asyncpg for hot paths** — if `DATABASE_URL` is available, direct PostgreSQL connections would eliminate PostgREST HTTP overhead
4. **Consider short-lived user cache** — cache `current_user` lookup for 15-30 seconds to eliminate 1 query per request
5. **Monitor logs** — watch for `SLOW REQUEST` and `SLOW QUERY` warnings to identify remaining bottlenecks

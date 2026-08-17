"""Request profiling middleware.

Logs total request time, database query time, and slow queries (>200 ms)
for every API request. Uses contextvars to track DB time per-request.
"""
import logging
import time
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("eduspace.profiling")

# Contextvars to track DB time and query count per request
db_time_ms: ContextVar[float] = ContextVar("db_time_ms", default=0.0)
db_query_count: ContextVar[int] = ContextVar("db_query_count", default=0)
slow_queries: ContextVar[list] = ContextVar("slow_queries", default=None)

SLOW_QUERY_THRESHOLD_MS = 200.0


def record_db_query(duration_ms: float, label: str = "") -> None:
    """Called by the DB wrapper to accumulate per-request DB time."""
    db_time_ms.set(db_time_ms.get() + duration_ms)
    db_query_count.set(db_query_count.get() + 1)
    if duration_ms > SLOW_QUERY_THRESHOLD_MS:
        sq = slow_queries.get()
        if sq is not None:
            sq.append({"label": label, "ms": round(duration_ms, 1)})


class ProfilingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Skip health checks and non-API routes
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # Reset contextvars for this request
        db_time_ms.set(0.0)
        db_query_count.set(0)
        slow_queries.set([])

        start = time.perf_counter()
        response = await call_next(request)
        total_ms = (time.perf_counter() - start) * 1000

        db_ms = db_time_ms.get()
        q_count = db_query_count.get()
        sq_list = slow_queries.get() or []
        processing_ms = total_ms - db_ms

        # Build log line
        method = request.method
        status_code = response.status_code
        log_parts = [
            f"{method} {path}",
            f"total={total_ms:.0f}ms",
            f"db={db_ms:.0f}ms",
            f"proc={processing_ms:.0f}ms",
            f"queries={q_count}",
        ]
        if sq_list:
            sq_summary = ", ".join(f"{q['label']}={q['ms']}ms" for q in sq_list)
            log_parts.append(f"SLOW[{sq_summary}]")

        log_line = " | ".join(log_parts)

        # Log at INFO for all API requests, WARNING for slow requests
        if total_ms > 1000:
            logger.warning("SLOW REQUEST: %s", log_line)
        elif total_ms > 500:
            logger.info("SLOW: %s", log_line)
        else:
            logger.info("%s", log_line)

        # Add timing headers to response
        response.headers["X-Total-Time-ms"] = f"{total_ms:.0f}"
        response.headers["X-DB-Time-ms"] = f"{db_ms:.0f}"
        response.headers["X-Query-Count"] = str(q_count)

        return response

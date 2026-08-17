"""Reusable Supabase client.

Supabase is used strictly as PostgreSQL storage (via the service-role key,
which bypasses Row Level Security). Authentication/authorization is handled by
the FastAPI application itself, not Supabase Auth.

The async client is created lazily and cached as a process-wide singleton.

A TimedQueryBuilder proxy wraps every .execute() call to record DB time
and slow queries per-request (tracked via contextvars in middleware/profiling.py).
"""
import logging
import time
from typing import Optional

from supabase import AsyncClient, acreate_client
from supabase.lib.client_options import AsyncClientOptions

from config import get_settings

logger = logging.getLogger("eduspace.database")

_client: Optional[AsyncClient] = None


class TimedQueryBuilder:
    """Proxy that wraps a Supabase query builder to time .execute() calls.

    All chainable methods (select, eq, order, limit, insert, update, etc.)
    return a new TimedQueryBuilder so the chain is preserved.
    The final .execute() call is timed and recorded via contextvars.
    """

    __slots__ = ("_builder", "_table")

    def __init__(self, builder, table_name: str = ""):
        object.__setattr__(self, "_builder", builder)
        object.__setattr__(self, "_table", table_name)

    def __getattr__(self, name):
        attr = getattr(self._builder, name)
        if name == "execute":
            async def timed_execute(*args, **kwargs):
                start = time.perf_counter()
                result = await attr(*args, **kwargs)
                duration_ms = (time.perf_counter() - start) * 1000
                try:
                    from middleware.profiling import record_db_query
                    record_db_query(duration_ms, self._table)
                except ImportError:
                    pass
                if duration_ms > 200:
                    logger.warning("SLOW QUERY %s: %.0fms", self._table, duration_ms)
                return result
            return timed_execute
        # Chainable method — return wrapped result
        def wrapped(*args, **kwargs):
            result = attr(*args, **kwargs)
            if result is self._builder:
                return self
            return TimedQueryBuilder(result, self._table)
        return wrapped


class TimedClient:
    """Proxy around AsyncClient that wraps .table() calls with timing."""

    __slots__ = ("_client",)

    def __init__(self, client: AsyncClient):
        object.__setattr__(self, "_client", client)

    def __getattr__(self, name):
        if name == "table":
            def table_proxy(table_name):
                builder = self._client.table(table_name)
                return TimedQueryBuilder(builder, table_name)
            return table_proxy
        return getattr(self._client, name)


async def init_supabase() -> AsyncClient:
    """Create and cache the Supabase async client. Call once on startup."""
    global _client
    if _client is not None:
        return _client

    settings = get_settings()
    settings.require_supabase()

    options = AsyncClientOptions(
        auto_refresh_token=False,
        persist_session=False,
    )
    _client = await acreate_client(
        settings.supabase_url,
        settings.supabase_service_role_key,
        options=options,
    )
    logger.info("Supabase client initialized for %s", settings.supabase_url)
    return _client


def get_client() -> TimedClient:
    """Return a timing-wrapped Supabase client.

    All .table().execute() calls will be timed and recorded for profiling.
    Raises if :func:`init_supabase` has not been awaited yet.
    """
    if _client is None:
        raise RuntimeError("Supabase client not initialized. Call init_supabase() first.")
    return TimedClient(_client)


async def close_supabase() -> None:
    global _client
    _client = None

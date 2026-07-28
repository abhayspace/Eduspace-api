"""Reusable Supabase client.

Supabase is used strictly as PostgreSQL storage (via the service-role key,
which bypasses Row Level Security). Authentication/authorization is handled by
the FastAPI application itself, not Supabase Auth.

The async client is created lazily and cached as a process-wide singleton.
"""
import logging
from typing import Optional

from supabase import AsyncClient, acreate_client
from supabase.lib.client_options import AsyncClientOptions

from config import get_settings

logger = logging.getLogger("eduspace.database")

_client: Optional[AsyncClient] = None


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


def get_client() -> AsyncClient:
    """Return the initialized Supabase client.

    Raises if :func:`init_supabase` has not been awaited yet.
    """
    if _client is None:
        raise RuntimeError("Supabase client not initialized. Call init_supabase() first.")
    return _client


async def close_supabase() -> None:
    global _client
    _client = None

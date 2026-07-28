"""Sequential fee receipt numbers: PREFIX-YEAR-NNNNNN (e.g. SMW-2026-000001)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from database import get_client

logger = logging.getLogger("eduspace.receipt.number")


def receipt_prefix_from_school(school: dict) -> str:
    """Derive a short uppercase prefix for the school."""
    code = (school.get("institution_code") or "").strip().upper()
    letters = re.sub(r"[^A-Z]", "", code)
    if len(letters) >= 3:
        return letters[:3]
    name = (school.get("school_name") or school.get("name") or "EDS").strip().upper()
    words = re.findall(r"[A-Z]+", name)
    if len(words) >= 2:
        joined = "".join(w[0] for w in words[:3])
        if len(joined) >= 2:
            return (joined + "X")[:3]
    compact = re.sub(r"[^A-Z]", "", name)
    if len(compact) >= 3:
        return compact[:3]
    return (compact + "EDS")[:3]


async def next_receipt_number(school_id: str, school: Optional[dict] = None) -> str:
    """Allocate the next unique receipt number for this school and year.

    Uses Postgres function ``next_fee_receipt_seq`` when available; falls back
    to counter table upsert via Supabase client.
    """
    year = datetime.now(timezone.utc).year
    prefix = receipt_prefix_from_school(school or {})
    seq = await _next_seq(school_id, year)
    number = f"{prefix}-{year}-{seq:06d}"
    logger.info("allocated receipt_number=%s school=%s", number, school_id)
    return number


async def _next_seq(school_id: str, year: int) -> int:
    client = get_client()
    # Prefer RPC if the migration function is exposed via PostgREST
    try:
        res = await client.rpc(
            "next_fee_receipt_seq",
            {"p_school_id": school_id, "p_year": year},
        ).execute()
        data = res.data
        if isinstance(data, int):
            return data
        if isinstance(data, list) and data:
            return int(data[0])
        if data is not None:
            return int(data)
    except Exception as exc:
        logger.warning("next_fee_receipt_seq RPC unavailable, using counter fallback: %s", exc)

    # Fallback: read-modify-write with unique receipt_number as safety net
    existing = (
        await client.table("fee_receipt_counters")
        .select("last_value")
        .eq("school_id", school_id)
        .eq("year", year)
        .limit(1)
        .execute()
    )
    if existing.data:
        current = int(existing.data[0].get("last_value") or 0)
        nxt = current + 1
        updated = (
            await client.table("fee_receipt_counters")
            .update({"last_value": nxt, "updated_at": datetime.now(timezone.utc).isoformat()})
            .eq("school_id", school_id)
            .eq("year", year)
            .eq("last_value", current)
            .execute()
        )
        if updated.data:
            return nxt
        # Contention — retry once
        return await _next_seq(school_id, year)

    inserted = (
        await client.table("fee_receipt_counters")
        .insert(
            {
                "school_id": school_id,
                "year": year,
                "last_value": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .execute()
    )
    if inserted.data:
        return 1
    raise HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Could not allocate receipt number",
    )

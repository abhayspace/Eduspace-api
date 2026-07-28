"""School payment gateway configuration CRUD."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

from database import get_client
from services.payment.gateway_base import GatewayCredentials
from services.payment.gateway_factory import create_gateway, supported_gateways
from utils.credential_crypto import decrypt_secret, encrypt_secret, mask_secret

SENSITIVE_FIELDS = (
    "key_secret",
    "salt_key",
    "client_secret",
    "webhook_secret",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _raise_missing(exc: APIError) -> None:
    if getattr(exc, "code", None) == "PGRST205":
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Database table 'school_payment_gateways' is missing. "
            "Run migrations/036_school_payment_gateways.sql or python migrate.py",
        ) from exc
    raise exc


def _encrypt_row(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    for field in SENSITIVE_FIELDS:
        if field in out and out[field] is not None:
            out[field] = encrypt_secret(str(out[field])) if str(out[field]).strip() else None
    return out


def _public_row(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    for field in SENSITIVE_FIELDS:
        if field in out:
            out[field] = mask_secret(out.get(field))
            out[f"{field}_set"] = bool(row.get(field))
    out["gateway_name"] = (out.get("gateway_name") or "").lower()
    return out


def _decrypt_credentials(row: dict[str, Any]) -> GatewayCredentials:
    return GatewayCredentials(
        gateway_name=(row.get("gateway_name") or "").lower(),
        merchant_name=row.get("merchant_name"),
        merchant_id=row.get("merchant_id"),
        key_id=row.get("key_id"),
        key_secret=decrypt_secret(row.get("key_secret")),
        salt_key=decrypt_secret(row.get("salt_key")),
        salt_index=row.get("salt_index"),
        client_id=row.get("client_id"),
        client_secret=decrypt_secret(row.get("client_secret")),
        webhook_secret=decrypt_secret(row.get("webhook_secret")),
        environment=row.get("environment") or "Sandbox",
        currency=row.get("currency") or "INR",
    )


async def get_active_gateway_row(school_id: str) -> Optional[dict[str, Any]]:
    client = get_client()
    try:
        res = (
            await client.table("school_payment_gateways")
            .select("*")
            .eq("school_id", school_id)
            .eq("active", True)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        _raise_missing(exc)
    return (res.data or [None])[0]


async def get_gateway_public(school_id: str) -> dict[str, Any]:
    row = await get_active_gateway_row(school_id)
    return {
        "configured": bool(row),
        "supported_gateways": supported_gateways(),
        "gateway": _public_row(row) if row else None,
    }


async def upsert_gateway(school_id: str, body: dict[str, Any], *, replace_secrets: bool) -> dict[str, Any]:
    gateway_name = (body.get("gateway_name") or "").strip().lower()
    if gateway_name not in supported_gateways():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported gateway. Supported: {', '.join(supported_gateways())}",
        )

    existing = await get_active_gateway_row(school_id)
    now = _now()
    payload: dict[str, Any] = {
        "school_id": school_id,
        "gateway_name": gateway_name,
        "merchant_name": body.get("merchant_name"),
        "merchant_id": body.get("merchant_id"),
        "key_id": body.get("key_id"),
        "salt_index": body.get("salt_index"),
        "client_id": body.get("client_id"),
        "environment": body.get("environment") or "Sandbox",
        "currency": body.get("currency") or "INR",
        "active": True,
        "updated_at": now,
    }

    # Secrets: keep existing when blank on update unless replace_secrets
    for field in SENSITIVE_FIELDS:
        incoming = body.get(field)
        if incoming is not None and str(incoming).strip() and not str(incoming).startswith("****"):
            payload[field] = encrypt_secret(str(incoming).strip())
        elif existing and not replace_secrets:
            payload[field] = existing.get(field)
        else:
            payload[field] = None

    client = get_client()
    try:
        if existing:
            # Deactivate others first if gateway change creates new row — we update in place.
            res = (
                await client.table("school_payment_gateways")
                .update(payload)
                .eq("id", existing["id"])
                .execute()
            )
            row = (res.data or [None])[0] or {**existing, **payload}
        else:
            payload["created_at"] = now
            # Ensure only one active: deactivate any leftovers
            await (
                client.table("school_payment_gateways")
                .update({"active": False, "updated_at": now})
                .eq("school_id", school_id)
                .eq("active", True)
                .execute()
            )
            res = await client.table("school_payment_gateways").insert(payload).execute()
            row = (res.data or [None])[0]
            if not row:
                row = await get_active_gateway_row(school_id)
    except APIError as exc:
        _raise_missing(exc)

    if not row:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save gateway")
    return _public_row(row)


async def disable_gateway(school_id: str) -> dict[str, Any]:
    row = await get_active_gateway_row(school_id)
    if not row:
        return {"ok": True, "disabled": False}
    client = get_client()
    await (
        client.table("school_payment_gateways")
        .update({"active": False, "updated_at": _now()})
        .eq("id", row["id"])
        .execute()
    )
    return {"ok": True, "disabled": True}


async def test_gateway(school_id: str) -> dict[str, Any]:
    row = await get_active_gateway_row(school_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active payment gateway configured")
    gateway = create_gateway(_decrypt_credentials(row))
    ok, message = await gateway.test_connection()
    return {"ok": ok, "message": message, "gateway_name": row.get("gateway_name")}


async def load_gateway_for_school(school_id: str):
    row = await get_active_gateway_row(school_id)
    if not row:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "School has no active payment gateway. Configure one in Fees → School payment gateway.",
        )
    return create_gateway(_decrypt_credentials(row)), row

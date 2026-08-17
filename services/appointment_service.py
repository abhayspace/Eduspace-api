"""Appointment requests: students submit, the school (principal/vice_principal/school_admin) approves or rejects."""
from datetime import date, datetime, timedelta, timezone
from typing import List

from fastapi import HTTPException, status

from database import get_client
from schemas.appointments import (
    AppointmentCancelIn,
    AppointmentDecisionIn,
    AppointmentIn,
    AppointmentOut,
)

TABLE = "appointments"
RETENTION_DAYS = 90

# Roles that review appointment requests instead of submitting them.
REVIEWER_ROLES = {"school_admin", "principal", "vice_principal", "super_admin"}


def _out(row: dict) -> AppointmentOut:
    return AppointmentOut(
        id=row["id"],
        user_id=row["user_id"],
        user_name=row.get("user_name") or "",
        user_role=row.get("user_role") or "",
        title=row.get("title") or "",
        requested_with=row.get("requested_with") or "principal",
        appointment_date=row["appointment_date"],
        appointment_time=row.get("appointment_time") or "",
        description=row.get("description") or "",
        status=row.get("status") or "pending",
        reviewed_by_user_id=row.get("reviewed_by_user_id"),
        reviewed_at=row.get("reviewed_at"),
        created_at=row.get("created_at"),
    )


async def _row(school_id: str, request_id: str) -> dict:
    client = get_client()
    res = (
        await client.table(TABLE)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", request_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Appointment request not found")
    return res.data[0]


async def _purge_expired(school_id: str) -> None:
    """Delete appointment requests older than RETENTION_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    client = get_client()
    await client.table(TABLE).delete().eq("school_id", school_id).lt("created_at", cutoff).execute()


async def list_appointments(school_id: str, user: dict) -> List[AppointmentOut]:
    await _purge_expired(school_id)
    client = get_client()
    query = client.table(TABLE).select("*").eq("school_id", school_id)
    if user["role"] not in REVIEWER_ROLES:
        query = query.eq("user_id", user["id"])
    res = await query.order("created_at", desc=True).limit(500).execute()
    return [_out(row) for row in res.data or []]


async def list_appointment_history(school_id: str, user: dict) -> List[AppointmentOut]:
    """Return expired/archived appointment requests (appointment_date < today)."""
    await _purge_expired(school_id)
    today_iso = date.today().isoformat()
    client = get_client()
    query = client.table(TABLE).select("*").eq("school_id", school_id).lt("appointment_date", today_iso)
    if user["role"] not in REVIEWER_ROLES:
        query = query.eq("user_id", user["id"])
    res = await query.order("created_at", desc=True).limit(200).execute()
    return [_out(row) for row in res.data or []]


async def create_appointment(school_id: str, user: dict, body: AppointmentIn) -> AppointmentOut:
    if user["role"] in REVIEWER_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The school reviews appointment requests and cannot create one"
        )

    client = get_client()
    res = (
        await client.table(TABLE)
        .insert(
            {
                "school_id": school_id,
                "user_id": user["id"],
                "user_name": user.get("full_name") or "",
                "user_role": user["role"],
                "title": body.title.strip(),
                "requested_with": body.requested_with,
                "appointment_date": body.appointment_date.isoformat(),
                "appointment_time": body.appointment_time.strip(),
                "description": body.description.strip(),
                "status": "pending",
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create appointment request")
    return _out(res.data[0])


async def update_appointment(
    school_id: str, user: dict, request_id: str, body: AppointmentIn
) -> AppointmentOut:
    row = await _row(school_id, request_id)
    is_reviewer = user["role"] in REVIEWER_ROLES
    if not is_reviewer and row["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only edit your own request")
    if not is_reviewer and row.get("status") != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only pending requests can be edited")

    client = get_client()
    res = (
        await client.table(TABLE)
        .update(
            {
                "title": body.title.strip(),
                "requested_with": body.requested_with,
                "appointment_date": body.appointment_date.isoformat(),
                "appointment_time": body.appointment_time.strip(),
                "description": body.description.strip(),
            }
        )
        .eq("id", request_id)
        .execute()
    )
    if res.data:
        return _out(res.data[0])
    return _out(await _row(school_id, request_id))


async def delete_appointment(school_id: str, user: dict, request_id: str) -> None:
    row = await _row(school_id, request_id)
    if row["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own request")
    client = get_client()
    await client.table(TABLE).delete().eq("id", request_id).execute()


async def decide_appointment(
    school_id: str, user: dict, request_id: str, body: AppointmentDecisionIn
) -> AppointmentOut:
    row = await _row(school_id, request_id)
    client = get_client()
    res = (
        await client.table(TABLE)
        .update(
            {
                "status": body.status,
                "reviewed_by_user_id": user["id"],
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", request_id)
        .execute()
    )
    if res.data:
        return _out(res.data[0])
    return _out(await _row(school_id, request_id))


async def cancel_appointment(
    school_id: str, user: dict, request_id: str, body: AppointmentCancelIn
) -> AppointmentOut:
    """Allow the requester to cancel an approved appointment request."""
    row = await _row(school_id, request_id)
    if row["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only cancel your own request")
    if row.get("status") != "approved":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only approved requests can be cancelled")
    client = get_client()
    res = (
        await client.table(TABLE)
        .update(
            {
                "status": "cancelled",
                "reviewed_by_user_id": user["id"],
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("id", request_id)
        .execute()
    )
    if res.data:
        return _out(res.data[0])
    return _out(await _row(school_id, request_id))

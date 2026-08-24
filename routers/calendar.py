"""School calendar — holidays, birthdays, and special days."""
from fastapi import APIRouter, Depends

from schemas.calendar import (
    CalendarEventCreateIn,
    CalendarEventOut,
    CalendarEventUpdateIn,
    CalendarMonthOut,
    CalendarSettingsOut,
    CalendarSettingsUpdateIn,
)
from services import calendar_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/calendar", tags=["calendar"])

_WRITE_ROLES = ("school_admin", "principal", "vice_principal", "super_admin")


@router.get("/settings", response_model=CalendarSettingsOut)
async def get_settings(
    user: dict = Depends(current_user),
) -> CalendarSettingsOut:
    return await calendar_service.get_settings(user["school_id"])


@router.put("/settings", response_model=CalendarSettingsOut)
async def update_settings(
    body: CalendarSettingsUpdateIn,
    user: dict = Depends(require_roles(*_WRITE_ROLES)),
) -> CalendarSettingsOut:
    return await calendar_service.update_settings(user["school_id"], body.open_on_sunday)


@router.get("/month", response_model=CalendarMonthOut)
async def get_month(
    month: int,
    year: int,
    user: dict = Depends(current_user),
) -> CalendarMonthOut:
    return await calendar_service.list_month(user["school_id"], month, year, user)


@router.post("/events", response_model=CalendarEventOut)
async def create_event(
    body: CalendarEventCreateIn,
    user: dict = Depends(require_roles(*_WRITE_ROLES)),
) -> CalendarEventOut:
    created_by = user.get("full_name") or user.get("email") or "Admin"
    return await calendar_service.create_event(user["school_id"], body, created_by)


@router.patch("/events/{event_id}", response_model=CalendarEventOut)
async def update_event(
    event_id: str,
    body: CalendarEventUpdateIn,
    user: dict = Depends(require_roles(*_WRITE_ROLES)),
) -> CalendarEventOut:
    return await calendar_service.update_event(user["school_id"], event_id, body)


@router.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
    user: dict = Depends(require_roles(*_WRITE_ROLES)),
) -> dict:
    await calendar_service.delete_event(user["school_id"], event_id)
    return {"ok": True}

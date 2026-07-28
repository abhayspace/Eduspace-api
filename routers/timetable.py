"""Class timetable (read-only for the app; scoped per school)."""
from typing import List, Optional

from fastapi import APIRouter, Depends

from database import get_client
from schemas.content import TimetableSlot
from utils.deps import current_user

router = APIRouter(prefix="/timetable", tags=["timetable"])

_COLUMNS = "id,school_id,class_name,day,start_time,end_time,subject,teacher,room"


def _to_slot(row: dict) -> TimetableSlot:
    return TimetableSlot(
        id=row["id"],
        school_id=row["school_id"],
        class_name=row["class_name"],
        day=row["day"],
        start=row["start_time"],
        end=row["end_time"],
        subject=row["subject"],
        teacher=row["teacher"],
        room=row.get("room", ""),
    )


@router.get("", response_model=List[TimetableSlot])
async def list_timetable(
    class_name: Optional[str] = None, user: dict = Depends(current_user)
) -> List[TimetableSlot]:
    client = get_client()
    query = client.table("timetable").select(_COLUMNS).eq("school_id", user["school_id"])
    if class_name:
        query = query.eq("class_name", class_name)
    res = await query.limit(500).execute()
    return [_to_slot(row) for row in (res.data or [])]

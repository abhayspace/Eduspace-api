"""Push device registration + in-app notifications."""
from typing import List

from fastapi import APIRouter, Depends, status

from database import get_client
from schemas.content import NotificationItem, RegisterPushIn
from services.notification_service import register_device
from utils.deps import current_user

router = APIRouter(tags=["notifications"])

_COLUMNS = "id,school_id,user_id,title,body,is_read,created_at"


@router.post("/register-push", status_code=status.HTTP_201_CREATED)
async def register_push(body: RegisterPushIn) -> dict:
    # Best-effort: never break the auth flow if registration fails.
    await register_device(body.user_id, body.platform, body.device_token)
    return {"status": "registered"}


@router.get("/notifications", response_model=List[NotificationItem])
async def list_notifications(user: dict = Depends(current_user)) -> List[NotificationItem]:
    client = get_client()
    res = (
        await client.table("notifications")
        .select(_COLUMNS)
        .eq("school_id", user["school_id"])
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    return [NotificationItem(**row) for row in (res.data or [])]

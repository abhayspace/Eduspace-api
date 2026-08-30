"""Complaints & Behaviour Management — router."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status

from schemas.complaints_behaviour import (
    BehaviourRecordCreateIn,
    BehaviourRecordOut,
    BehaviourRecordUpdateIn,
    ComplaintAnalyticsOut,
    ComplaintAssignIn,
    ComplaintCreateIn,
    ComplaintNoteIn,
    ComplaintOut,
    ComplaintStatusUpdateIn,
    ComplaintUpdateIn,
    DisciplinaryActionCreateIn,
    DisciplinaryActionOut,
)
from services import complaints_behaviour_service as svc
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/complaints-behaviour", tags=["complaints-behaviour"])

_admin_dep = require_roles("school_admin", "principal", "vice_principal", "super_admin")
_staff_dep = require_roles("school_admin", "principal", "vice_principal", "super_admin", "teacher")


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

@router.get("/complaints", response_model=List[ComplaintOut])
async def list_complaints(
    status: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    severity: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(current_user),
) -> List[ComplaintOut]:
    return await svc.list_complaints(user["school_id"], user, status, category, severity, search, limit)


@router.get("/complaints/{complaint_id}", response_model=ComplaintOut)
async def get_complaint(
    complaint_id: str,
    user: dict = Depends(current_user),
) -> ComplaintOut:
    return await svc.get_complaint(user["school_id"], complaint_id, user)


@router.post("/complaints", response_model=ComplaintOut, status_code=status.HTTP_201_CREATED)
async def create_complaint(
    body: ComplaintCreateIn,
    user: dict = Depends(current_user),
) -> ComplaintOut:
    return await svc.create_complaint(user["school_id"], user, body)


@router.put("/complaints/{complaint_id}", response_model=ComplaintOut)
async def update_complaint(
    complaint_id: str,
    body: ComplaintUpdateIn,
    user: dict = Depends(current_user),
) -> ComplaintOut:
    return await svc.update_complaint(user["school_id"], complaint_id, user, body)


@router.put("/complaints/{complaint_id}/status", response_model=ComplaintOut)
async def change_complaint_status(
    complaint_id: str,
    body: ComplaintStatusUpdateIn,
    user: dict = Depends(_admin_dep),
) -> ComplaintOut:
    return await svc.change_complaint_status(user["school_id"], complaint_id, user, body)


@router.put("/complaints/{complaint_id}/assign", response_model=ComplaintOut)
async def assign_complaint(
    complaint_id: str,
    body: ComplaintAssignIn,
    user: dict = Depends(_admin_dep),
) -> ComplaintOut:
    return await svc.assign_complaint(user["school_id"], complaint_id, user, body)


@router.post("/complaints/{complaint_id}/notes", response_model=ComplaintOut)
async def add_complaint_note(
    complaint_id: str,
    body: ComplaintNoteIn,
    user: dict = Depends(_staff_dep),
) -> ComplaintOut:
    return await svc.add_complaint_note(user["school_id"], complaint_id, user, body)


@router.delete("/complaints/{complaint_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_complaint(
    complaint_id: str,
    user: dict = Depends(current_user),
):
    await svc.delete_complaint(user["school_id"], complaint_id, user)


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

@router.get("/behaviour", response_model=List[BehaviourRecordOut])
async def list_behaviour(
    type: Optional[str] = Query(default=None),
    category: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(current_user),
) -> List[BehaviourRecordOut]:
    return await svc.list_behaviour(user["school_id"], user, type, category, search, limit)


@router.post("/behaviour", response_model=BehaviourRecordOut, status_code=status.HTTP_201_CREATED)
async def create_behaviour(
    body: BehaviourRecordCreateIn,
    user: dict = Depends(_staff_dep),
) -> BehaviourRecordOut:
    return await svc.create_behaviour(user["school_id"], user, body)


@router.put("/behaviour/{record_id}", response_model=BehaviourRecordOut)
async def update_behaviour(
    record_id: str,
    body: BehaviourRecordUpdateIn,
    user: dict = Depends(_staff_dep),
) -> BehaviourRecordOut:
    return await svc.update_behaviour(user["school_id"], record_id, user, body)


@router.delete("/behaviour/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_behaviour(
    record_id: str,
    user: dict = Depends(_staff_dep),
):
    await svc.delete_behaviour(user["school_id"], record_id, user)


# ---------------------------------------------------------------------------
# Disciplinary actions
# ---------------------------------------------------------------------------

@router.get("/disciplinary", response_model=List[DisciplinaryActionOut])
async def list_disciplinary(
    student_id: Optional[str] = Query(default=None),
    user: dict = Depends(current_user),
) -> List[DisciplinaryActionOut]:
    return await svc.list_disciplinary(user["school_id"], user, student_id)


@router.post("/disciplinary", response_model=DisciplinaryActionOut, status_code=status.HTTP_201_CREATED)
async def create_disciplinary(
    body: DisciplinaryActionCreateIn,
    user: dict = Depends(_admin_dep),
) -> DisciplinaryActionOut:
    return await svc.create_disciplinary(user["school_id"], user, body)


# ---------------------------------------------------------------------------
# Analytics (admin)
# ---------------------------------------------------------------------------

@router.get("/analytics", response_model=ComplaintAnalyticsOut)
async def get_analytics(
    user: dict = Depends(_admin_dep),
) -> ComplaintAnalyticsOut:
    return await svc.get_analytics(user["school_id"], user)

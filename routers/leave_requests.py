"""Leave request routes: teacher/staff/student submit, the school approves or rejects."""
from typing import List

from fastapi import APIRouter, Depends, Response, status

from schemas.leave_requests import (
    LeaveRequestCancelIn,
    LeaveRequestDecisionIn,
    LeaveRequestIn,
    LeaveRequestOut,
)
from services import leave_request_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/leave-requests", tags=["leave-requests"])

# Admins review teacher/staff requests; class teachers review student requests.
reviewer_only = require_roles("school_admin", "principal", "vice_principal", "teacher")


@router.get("", response_model=List[LeaveRequestOut])
async def list_leave_requests(user: dict = Depends(current_user)) -> List[LeaveRequestOut]:
    return await leave_request_service.list_leave_requests(user["school_id"], user)


@router.get("/history", response_model=List[LeaveRequestOut])
async def list_leave_history(user: dict = Depends(current_user)) -> List[LeaveRequestOut]:
    return await leave_request_service.list_leave_history(user["school_id"], user)


@router.post("", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED)
async def create_leave_request(
    body: LeaveRequestIn,
    user: dict = Depends(current_user),
) -> LeaveRequestOut:
    return await leave_request_service.create_leave_request(user["school_id"], user, body)


@router.put("/{request_id}", response_model=LeaveRequestOut)
async def update_leave_request(
    request_id: str,
    body: LeaveRequestIn,
    user: dict = Depends(current_user),
) -> LeaveRequestOut:
    return await leave_request_service.update_leave_request(
        user["school_id"], user, request_id, body
    )


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_leave_request(request_id: str, user: dict = Depends(current_user)) -> Response:
    await leave_request_service.delete_leave_request(user["school_id"], user, request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{request_id}/decision", response_model=LeaveRequestOut)
async def decide_leave_request(
    request_id: str,
    body: LeaveRequestDecisionIn,
    user: dict = Depends(reviewer_only),
) -> LeaveRequestOut:
    return await leave_request_service.decide_leave_request(
        user["school_id"], user, request_id, body
    )


@router.post("/{request_id}/cancel", response_model=LeaveRequestOut)
async def cancel_leave_request(
    request_id: str,
    body: LeaveRequestCancelIn,
    user: dict = Depends(current_user),
) -> LeaveRequestOut:
    return await leave_request_service.cancel_leave_request(
        user["school_id"], user, request_id, body
    )

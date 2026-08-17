"""Appointment request routes: students submit, the school approves or rejects."""
from typing import List

from fastapi import APIRouter, Depends, Response, status

from schemas.appointments import (
    AppointmentCancelIn,
    AppointmentDecisionIn,
    AppointmentIn,
    AppointmentOut,
)
from services import appointment_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/appointments", tags=["appointments"])

reviewer_only = require_roles("school_admin", "principal", "vice_principal")


@router.get("", response_model=List[AppointmentOut])
async def list_appointments(user: dict = Depends(current_user)) -> List[AppointmentOut]:
    return await appointment_service.list_appointments(user["school_id"], user)


@router.get("/history", response_model=List[AppointmentOut])
async def list_appointment_history(user: dict = Depends(current_user)) -> List[AppointmentOut]:
    return await appointment_service.list_appointment_history(user["school_id"], user)


@router.post("", response_model=AppointmentOut, status_code=status.HTTP_201_CREATED)
async def create_appointment(
    body: AppointmentIn,
    user: dict = Depends(current_user),
) -> AppointmentOut:
    return await appointment_service.create_appointment(user["school_id"], user, body)


@router.put("/{request_id}", response_model=AppointmentOut)
async def update_appointment(
    request_id: str,
    body: AppointmentIn,
    user: dict = Depends(current_user),
) -> AppointmentOut:
    return await appointment_service.update_appointment(
        user["school_id"], user, request_id, body
    )


@router.delete("/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_appointment(request_id: str, user: dict = Depends(current_user)) -> Response:
    await appointment_service.delete_appointment(user["school_id"], user, request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{request_id}/decision", response_model=AppointmentOut)
async def decide_appointment(
    request_id: str,
    body: AppointmentDecisionIn,
    user: dict = Depends(reviewer_only),
) -> AppointmentOut:
    return await appointment_service.decide_appointment(
        user["school_id"], user, request_id, body
    )


@router.post("/{request_id}/cancel", response_model=AppointmentOut)
async def cancel_appointment(
    request_id: str,
    body: AppointmentCancelIn,
    user: dict = Depends(current_user),
) -> AppointmentOut:
    return await appointment_service.cancel_appointment(
        user["school_id"], user, request_id, body
    )

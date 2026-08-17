"""School medical room visit routes — school doctors add visits; school admins view."""
from typing import List

from fastapi import APIRouter, Depends, Response, status

from schemas.school_medical import (
    SchoolMedicalVisitIn,
    SchoolMedicalVisitOut,
)
from services import school_medical_service
from utils.deps import require_roles

router = APIRouter(prefix="/medical", tags=["school-medical"])

viewer_roles = require_roles("school_admin", "principal", "vice_principal", "school_doctor")
doctor_only = require_roles("school_doctor")


@router.get("/visits/today", response_model=List[SchoolMedicalVisitOut])
async def list_today_visits(user: dict = Depends(viewer_roles)) -> List[SchoolMedicalVisitOut]:
    return await school_medical_service.list_today_visits(user["school_id"])


@router.get("/visits/history", response_model=List[SchoolMedicalVisitOut])
async def list_visit_history(user: dict = Depends(viewer_roles)) -> List[SchoolMedicalVisitOut]:
    return await school_medical_service.list_visit_history(user["school_id"])


@router.post("/visits", response_model=SchoolMedicalVisitOut, status_code=status.HTTP_201_CREATED)
async def create_visit(
    body: SchoolMedicalVisitIn,
    user: dict = Depends(doctor_only),
) -> SchoolMedicalVisitOut:
    return await school_medical_service.create_visit(user["school_id"], user, body)


@router.delete("/visits/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_visit(visit_id: str, user: dict = Depends(doctor_only)) -> Response:
    await school_medical_service.delete_visit(user["school_id"], visit_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

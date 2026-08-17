"""School medical room visits: the school admin sees all visits for the school."""
from datetime import date
from typing import List

from fastapi import HTTPException, status

from database import get_client
from schemas.school_medical import SchoolMedicalVisitIn, SchoolMedicalVisitOut

TABLE = "teacher_medical_visits"


def _out(row: dict) -> SchoolMedicalVisitOut:
    return SchoolMedicalVisitOut(
        id=row["id"],
        user_id=row.get("user_id") or "",
        person_name=row.get("person_name") or "",
        person_role=row.get("person_role") or "",
        visit_date=row["visit_date"],
        visit_time=row.get("visit_time") or "",
        issue=row.get("issue") or "",
        treatment=row.get("treatment") or "",
        prescription=row.get("prescription") or "",
        attended_by=row.get("attended_by") or "",
        created_at=row.get("created_at"),
    )


async def list_today_visits(school_id: str) -> List[SchoolMedicalVisitOut]:
    """Return all medical room visits for today."""
    today_iso = date.today().isoformat()
    client = get_client()
    res = (
        await client.table(TABLE)
        .select("*")
        .eq("school_id", school_id)
        .eq("visit_date", today_iso)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return [_out(row) for row in (res.data or [])]


async def list_visit_history(school_id: str) -> List[SchoolMedicalVisitOut]:
    """Return all past medical room visits (before today)."""
    today_iso = date.today().isoformat()
    client = get_client()
    res = (
        await client.table(TABLE)
        .select("*")
        .eq("school_id", school_id)
        .lt("visit_date", today_iso)
        .order("visit_date", desc=True)
        .limit(500)
        .execute()
    )
    return [_out(row) for row in (res.data or [])]


async def create_visit(school_id: str, user: dict, body: SchoolMedicalVisitIn) -> SchoolMedicalVisitOut:
    client = get_client()
    res = (
        await client.table(TABLE)
        .insert(
            {
                "school_id": school_id,
                "user_id": user["id"],
                "person_name": body.person_name.strip(),
                "person_role": body.person_role.strip(),
                "visit_date": body.visit_date.isoformat(),
                "visit_time": body.visit_time.strip(),
                "issue": body.issue.strip(),
                "treatment": body.treatment.strip(),
                "prescription": body.prescription.strip(),
                "attended_by": body.attended_by.strip(),
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create medical visit")
    return _out(res.data[0])


async def delete_visit(school_id: str, visit_id: str) -> None:
    client = get_client()
    await client.table(TABLE).delete().eq("school_id", school_id).eq("id", visit_id).execute()

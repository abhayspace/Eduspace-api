"""Leave requests: teacher/staff/student submit, the school approves or rejects."""
from datetime import date, datetime, timedelta, timezone
from typing import List

from fastapi import HTTPException, status

from database import get_client
from schemas.leave_requests import (
    LeaveRequestCancelIn,
    LeaveRequestDecisionIn,
    LeaveRequestIn,
    LeaveRequestOut,
)

TABLE = "leave_requests"
RETENTION_DAYS = 90

# Roles that review leave requests instead of submitting them.
REVIEWER_ROLES = {"school_admin", "principal", "vice_principal", "super_admin"}


def _out(row: dict) -> LeaveRequestOut:
    return LeaveRequestOut(
        id=row["id"],
        user_id=row["user_id"],
        user_name=row.get("user_name") or "",
        user_role=row.get("user_role") or "",
        title=row.get("title") or "",
        leave_type=row.get("leave_type") or "single",
        start_date=row["start_date"],
        end_date=row["end_date"],
        description=row.get("description") or "",
        status=row.get("status") or "pending",
        reviewed_by_user_id=row.get("reviewed_by_user_id"),
        reviewed_at=row.get("reviewed_at"),
        created_at=row.get("created_at"),
        reviewer_user_id=row.get("reviewer_user_id"),
        reviewer_role=row.get("reviewer_role") or "admin",
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
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Leave request not found")
    return res.data[0]


async def _purge_expired(school_id: str) -> None:
    """Delete leave requests older than RETENTION_DAYS."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    client = get_client()
    await client.table(TABLE).delete().eq("school_id", school_id).lt("created_at", cutoff).execute()


async def _find_class_teacher_user_id(school_id: str, student_user_id: str) -> str | None:
    """Find the class teacher's user_id for a given student."""
    client = get_client()
    # Get the student's class_id and section_id
    stu_res = (
        await client.table("students")
        .select("class_id,section_id")
        .eq("school_id", school_id)
        .eq("user_id", student_user_id)
        .limit(1)
        .execute()
    )
    if not stu_res.data:
        return None
    profile = stu_res.data[0]
    class_id = profile.get("class_id")
    section_id = profile.get("section_id")
    if not class_id or not section_id:
        return None
    # Find the class teacher assigned to this class+section
    ct_res = (
        await client.table("teachers")
        .select("user_id")
        .eq("school_id", school_id)
        .eq("is_class_teacher", True)
        .eq("class_teacher_class_id", class_id)
        .eq("class_teacher_section_id", section_id)
        .limit(1)
        .execute()
    )
    if not ct_res.data:
        return None
    return ct_res.data[0].get("user_id")


async def _is_class_teacher(user: dict) -> bool:
    """Check if the current user is a class teacher."""
    if user.get("role") != "teacher":
        return False
    client = get_client()
    res = (
        await client.table("teachers")
        .select("is_class_teacher")
        .eq("school_id", user["school_id"])
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    return bool(res.data and res.data[0].get("is_class_teacher"))


def _is_active(row: dict, today: date | None = None) -> bool:
    """A request is 'active' if its end_date has not yet passed."""
    anchor = today or date.today()
    end = row.get("end_date")
    if not end:
        return False
    try:
        return date.fromisoformat(end) >= anchor
    except (ValueError, TypeError):
        return False


async def list_leave_requests(school_id: str, user: dict) -> List[LeaveRequestOut]:
    await _purge_expired(school_id)
    client = get_client()
    query = client.table(TABLE).select("*").eq("school_id", school_id)
    role = user["role"]
    if role in REVIEWER_ROLES:
        # Admins see teacher/staff requests (reviewer_role='admin')
        query = query.eq("reviewer_role", "admin")
    elif role == "teacher" and await _is_class_teacher(user):
        # Class teachers see student requests assigned to them
        query = query.eq("reviewer_role", "class_teacher").eq("reviewer_user_id", user["id"])
        # Also show their own requests
        res = await query.order("created_at", desc=True).limit(500).execute()
        own_res = (
            await client.table(TABLE)
            .select("*")
            .eq("school_id", school_id)
            .eq("user_id", user["id"])
            .order("created_at", desc=True)
            .limit(500)
            .execute()
        )
        combined = {r["id"]: r for r in (res.data or [])}
        for r in (own_res.data or []):
            combined[r["id"]] = r
        return [_out(row) for row in sorted(combined.values(), key=lambda r: r.get("created_at", ""), reverse=True)]
    else:
        # Students and regular teachers see only their own requests
        query = query.eq("user_id", user["id"])
    res = await query.order("created_at", desc=True).limit(500).execute()
    return [_out(row) for row in res.data or []]


async def list_leave_history(school_id: str, user: dict) -> List[LeaveRequestOut]:
    """Return expired/archived leave requests (end_date < today)."""
    await _purge_expired(school_id)
    today_iso = date.today().isoformat()
    client = get_client()
    query = client.table(TABLE).select("*").eq("school_id", school_id).lt("end_date", today_iso)
    role = user["role"]
    if role in REVIEWER_ROLES:
        query = query.eq("reviewer_role", "admin")
    elif role == "teacher" and await _is_class_teacher(user):
        query = query.eq("reviewer_role", "class_teacher").eq("reviewer_user_id", user["id"])
        res = await query.order("created_at", desc=True).limit(200).execute()
        own_res = (
            await client.table(TABLE)
            .select("*")
            .eq("school_id", school_id)
            .lt("end_date", today_iso)
            .eq("user_id", user["id"])
            .order("created_at", desc=True)
            .limit(200)
            .execute()
        )
        combined = {r["id"]: r for r in (res.data or [])}
        for r in (own_res.data or []):
            combined[r["id"]] = r
        return [_out(row) for row in sorted(combined.values(), key=lambda r: r.get("created_at", ""), reverse=True)]
    else:
        query = query.eq("user_id", user["id"])
    res = await query.order("created_at", desc=True).limit(200).execute()
    return [_out(row) for row in res.data or []]


async def create_leave_request(school_id: str, user: dict, body: LeaveRequestIn) -> LeaveRequestOut:
    if user["role"] in REVIEWER_ROLES:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "The school reviews leave requests and cannot create one"
        )
    if body.leave_type == "multiple" and body.end_date < body.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date cannot be before start date")
    end_date = body.end_date if body.leave_type == "multiple" else body.start_date

    # Route: student requests → class teacher, teacher/staff requests → admin
    reviewer_role = "admin"
    reviewer_user_id = None
    if user["role"] == "student":
        ct_id = await _find_class_teacher_user_id(school_id, user["id"])
        if ct_id:
            reviewer_role = "class_teacher"
            reviewer_user_id = ct_id

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
                "leave_type": body.leave_type,
                "start_date": body.start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "description": body.description.strip(),
                "status": "pending",
                "reviewer_role": reviewer_role,
                "reviewer_user_id": reviewer_user_id,
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create leave request")
    return _out(res.data[0])


async def update_leave_request(
    school_id: str, user: dict, request_id: str, body: LeaveRequestIn
) -> LeaveRequestOut:
    row = await _row(school_id, request_id)
    is_reviewer = user["role"] in REVIEWER_ROLES
    if not is_reviewer and row["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only edit your own request")
    if not is_reviewer and row.get("status") != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only pending requests can be edited")
    if body.leave_type == "multiple" and body.end_date < body.start_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date cannot be before start date")
    end_date = body.end_date if body.leave_type == "multiple" else body.start_date

    client = get_client()
    res = (
        await client.table(TABLE)
        .update(
            {
                "title": body.title.strip(),
                "leave_type": body.leave_type,
                "start_date": body.start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "description": body.description.strip(),
            }
        )
        .eq("id", request_id)
        .execute()
    )
    if res.data:
        return _out(res.data[0])
    return _out(await _row(school_id, request_id))


async def delete_leave_request(school_id: str, user: dict, request_id: str) -> None:
    row = await _row(school_id, request_id)
    if row["user_id"] != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own request")
    client = get_client()
    await client.table(TABLE).delete().eq("id", request_id).execute()


async def _auto_mark_teacher_leave(school_id: str, user_id: str, start_date: str, end_date: str) -> None:
    """Mark staff_attendance as 'leave' for each day in the date range."""
    from schemas.content import StaffAttendanceMarkIn
    from services import staff_attendance_service

    start = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    current = start
    while current <= end:
        day_iso = current.isoformat()
        try:
            await staff_attendance_service.mark_staff_attendance(
                school_id,
                StaffAttendanceMarkIn(user_id=user_id, date=day_iso, status="leave"),
                marked_by="Leave Request System",
            )
        except HTTPException:
            pass
        current += timedelta(days=1)


async def decide_leave_request(
    school_id: str, user: dict, request_id: str, body: LeaveRequestDecisionIn
) -> LeaveRequestOut:
    row = await _row(school_id, request_id)
    # Permission check: class teachers can only decide student requests
    # assigned to them; admins can decide teacher/staff requests.
    if user["role"] in REVIEWER_ROLES:
        if row.get("reviewer_role") == "class_teacher":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Student leave requests are reviewed by the class teacher",
            )
    elif user["role"] == "teacher" and await _is_class_teacher(user):
        if row.get("reviewer_role") != "class_teacher":
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "You can only review leave requests from students in your class",
            )
        if row.get("reviewer_user_id") != user["id"]:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "This leave request is assigned to a different class teacher",
            )
    else:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "You do not have permission to review leave requests"
        )
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
        updated = _out(res.data[0])
    else:
        updated = _out(await _row(school_id, request_id))

    if body.status == "approved" and row.get("user_role") in ("teacher", "principal", "vice_principal", "school_admin", "super_admin", "office_staff"):
        await _auto_mark_teacher_leave(
            school_id,
            row["user_id"],
            row["start_date"],
            row["end_date"],
        )

    return updated


async def cancel_leave_request(
    school_id: str, user: dict, request_id: str, body: LeaveRequestCancelIn
) -> LeaveRequestOut:
    """Allow the requester to cancel an approved leave request."""
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

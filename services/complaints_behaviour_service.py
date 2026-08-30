"""Complaints & Behaviour Management — service layer."""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.complaints_behaviour import (
    BehaviourRecordCreateIn,
    BehaviourRecordOut,
    BehaviourRecordUpdateIn,
    ComplaintActivityOut,
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

_ADMIN_ROLES = {"school_admin", "principal", "vice_principal", "super_admin"}
_STAFF_ROLES = {"school_admin", "principal", "vice_principal", "super_admin", "teacher"}

_COMPLAINT_COLUMNS = (
    "id,school_id,title,description,category,severity,status,is_anonymous,"
    "incident_date,submitted_by_user_id,submitted_by_name,submitted_by_role,"
    "student_id,student_name,involved_user_id,involved_name,"
    "assigned_to_user_id,assigned_to_name,resolution_notes,"
    "attachment_url,attachment_name,created_at,updated_at"
)
_ACTIVITY_COLUMNS = (
    "id,complaint_id,action,description,actor_name,actor_role,is_internal,created_at"
)
_BEHAVIOUR_COLUMNS = (
    "id,school_id,student_id,student_name,class_name,section_name,type,category,"
    "description,severity,incident_date,recorded_by_user_id,recorded_by_name,"
    "recorded_by_role,is_visible_to_student,created_at,updated_at"
)
_DISCIPLINARY_COLUMNS = (
    "id,school_id,student_id,student_name,behaviour_record_id,action_type,"
    "notes,status,action_date,created_by_name,created_at"
)


# ---------------------------------------------------------------------------
# Helper: resolve linked student for student/parent users
# ---------------------------------------------------------------------------

async def _resolve_linked_student_id(school_id: str, user: dict) -> Optional[str]:
    """Return the student_id linked to this user (student or parent)."""
    role = user.get("role", "")
    if role == "student":
        client = get_client()
        res = (
            await client.table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        return res.data[0]["id"] if res.data else None
    if role == "parent":
        client = get_client()
        res = (
            await client.table("parents")
            .select("student_id")
            .eq("school_id", school_id)
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        return res.data[0]["student_id"] if res.data and res.data[0].get("student_id") else None
    return None


def _is_admin(user: dict) -> bool:
    return user.get("role") in _ADMIN_ROLES or user.get("role") == "super_admin"


# ---------------------------------------------------------------------------
# Complaints — list
# ---------------------------------------------------------------------------

async def list_complaints(
    school_id: str,
    user: dict,
    status_filter: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
) -> List[ComplaintOut]:
    client = get_client()
    query = client.table("complaints").select(_COMPLAINT_COLUMNS).eq("school_id", school_id)

    role = user.get("role", "")
    # Student/parent: only see their own complaints
    if role in ("student", "parent"):
        query = query.eq("submitted_by_user_id", user["id"])
    # Teacher: see complaints they submitted or are assigned to
    elif role == "teacher":
        query = query.or_(f"submitted_by_user_id.eq.{user['id']},assigned_to_user_id.eq.{user['id']}")
    # Admin: see all (no extra filter)

    if status_filter:
        query = query.eq("status", status_filter)
    if category:
        query = query.eq("category", category)
    if severity:
        query = query.eq("severity", severity)

    query = query.order("created_at", desc=True).limit(limit)
    res = await query.execute()
    rows = res.data or []

    # Filter by search text (title or description)
    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r.get("title", "")).lower() or s in (r.get("description", "")).lower()]

    return [_row_to_complaint(r, user) for r in rows]


# ---------------------------------------------------------------------------
# Complaints — get by id
# ---------------------------------------------------------------------------

async def get_complaint(school_id: str, complaint_id: str, user: dict) -> ComplaintOut:
    client = get_client()
    res = (
        await client.table("complaints")
        .select(_COMPLAINT_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", complaint_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    row = res.data[0]

    # Permission check
    _check_complaint_access(row, user)

    # Load activity
    act_res = (
        await client.table("complaint_activity")
        .select(_ACTIVITY_COLUMNS)
        .eq("complaint_id", complaint_id)
        .order("created_at", desc=False)
        .execute()
    )
    activity = []
    for a in act_res.data or []:
        # Hide internal notes from students/parents
        if a.get("is_internal") and user.get("role") in ("student", "parent"):
            continue
        activity.append(ComplaintActivityOut(**a))

    out = _row_to_complaint(row, user)
    out.activity = activity
    return out


# ---------------------------------------------------------------------------
# Complaints — create
# ---------------------------------------------------------------------------

async def create_complaint(school_id: str, user: dict, body: ComplaintCreateIn) -> ComplaintOut:
    import uuid
    complaint_id = str(uuid.uuid4())

    # If student/parent, auto-link their student_id
    student_id = body.student_id
    student_name = body.student_name
    if user.get("role") in ("student", "parent") and not student_id:
        linked = await _resolve_linked_student_id(school_id, user)
        if linked:
            student_id = linked
            # Fetch student name
            client = get_client()
            s_res = await client.table("students").select("full_name").eq("id", linked).limit(1).execute()
            if s_res.data:
                student_name = s_res.data[0].get("full_name", "")

    # For anonymous complaints, hide submitter info from the record
    submitted_by_name = user.get("full_name", "")
    submitted_by_role = user.get("role", "")
    if body.is_anonymous:
        submitted_by_name = "Anonymous"
        submitted_by_role = ""

    client = get_client()
    row = {
        "id": complaint_id,
        "school_id": school_id,
        "title": body.title,
        "description": body.description,
        "category": body.category,
        "severity": body.severity,
        "status": "pending",
        "is_anonymous": body.is_anonymous,
        "incident_date": body.incident_date.isoformat() if body.incident_date else None,
        "submitted_by_user_id": user["id"],
        "submitted_by_name": submitted_by_name,
        "submitted_by_role": submitted_by_role,
        "student_id": student_id,
        "student_name": student_name,
        "involved_user_id": body.involved_user_id,
        "involved_name": body.involved_name,
        "attachment_url": body.attachment_url,
        "attachment_name": body.attachment_name,
    }
    await client.table("complaints").insert(row).execute()

    # Log activity
    await _log_activity(school_id, complaint_id, "created", "Complaint created", user, is_internal=False)

    return await get_complaint(school_id, complaint_id, user)


# ---------------------------------------------------------------------------
# Complaints — update
# ---------------------------------------------------------------------------

async def update_complaint(school_id: str, complaint_id: str, user: dict, body: ComplaintUpdateIn) -> ComplaintOut:
    client = get_client()
    res = (
        await client.table("complaints")
        .select(_COMPLAINT_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", complaint_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    row = res.data[0]
    _check_complaint_access(row, user)

    # Students/parents can only edit their own complaints and only certain fields
    is_author = row.get("submitted_by_user_id") == user["id"]
    is_admin = _is_admin(user)

    update_data: dict = {}
    if body.title is not None:
        if is_author or is_admin:
            update_data["title"] = body.title
    if body.description is not None:
        if is_author or is_admin:
            update_data["description"] = body.description
    if body.category is not None:
        update_data["category"] = body.category
    if body.severity is not None and is_admin:
        update_data["severity"] = body.severity
    if body.status is not None and is_admin:
        update_data["status"] = body.status
    if body.assigned_to_user_id is not None and is_admin:
        update_data["assigned_to_user_id"] = body.assigned_to_user_id
        update_data["assigned_to_name"] = body.assigned_to_name or ""
    if body.resolution_notes is not None and is_admin:
        update_data["resolution_notes"] = body.resolution_notes
    if body.is_anonymous is not None and is_author:
        update_data["is_anonymous"] = body.is_anonymous

    if update_data:
        update_data["updated_at"] = datetime.utcnow().isoformat()
        await client.table("complaints").update(update_data).eq("id", complaint_id).eq("school_id", school_id).execute()

    return await get_complaint(school_id, complaint_id, user)


# ---------------------------------------------------------------------------
# Complaints — change status (admin)
# ---------------------------------------------------------------------------

async def change_complaint_status(school_id: str, complaint_id: str, user: dict, body: ComplaintStatusUpdateIn) -> ComplaintOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can change complaint status")

    client = get_client()
    update_data = {"status": body.status, "updated_at": datetime.utcnow().isoformat()}
    if body.resolution_notes:
        update_data["resolution_notes"] = body.resolution_notes
    await client.table("complaints").update(update_data).eq("id", complaint_id).eq("school_id", school_id).execute()

    await _log_activity(school_id, complaint_id, "status_changed", f"Status changed to {body.status}", user, is_internal=False)
    if body.resolution_notes:
        await _log_activity(school_id, complaint_id, "resolution_added", "Resolution details added", user, is_internal=False)

    return await get_complaint(school_id, complaint_id, user)


# ---------------------------------------------------------------------------
# Complaints — assign (admin)
# ---------------------------------------------------------------------------

async def assign_complaint(school_id: str, complaint_id: str, user: dict, body: ComplaintAssignIn) -> ComplaintOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can assign complaints")

    client = get_client()
    await client.table("complaints").update({
        "assigned_to_user_id": body.assigned_to_user_id,
        "assigned_to_name": body.assigned_to_name,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", complaint_id).eq("school_id", school_id).execute()

    await _log_activity(school_id, complaint_id, "assigned", f"Assigned to {body.assigned_to_name}", user, is_internal=True)

    return await get_complaint(school_id, complaint_id, user)


# ---------------------------------------------------------------------------
# Complaints — add internal note (admin/teacher)
# ---------------------------------------------------------------------------

async def add_complaint_note(school_id: str, complaint_id: str, user: dict, body: ComplaintNoteIn) -> ComplaintOut:
    if user.get("role") not in _STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only staff can add notes")

    await _log_activity(school_id, complaint_id, "note_added", body.note, user, is_internal=body.is_internal)
    return await get_complaint(school_id, complaint_id, user)


# ---------------------------------------------------------------------------
# Complaints — delete (admin or author)
# ---------------------------------------------------------------------------

async def delete_complaint(school_id: str, complaint_id: str, user: dict) -> None:
    client = get_client()
    res = (
        await client.table("complaints")
        .select("submitted_by_user_id")
        .eq("school_id", school_id)
        .eq("id", complaint_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found")
    row = res.data[0]
    is_author = row.get("submitted_by_user_id") == user["id"]
    if not is_author and not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to delete this complaint")

    await client.table("complaint_activity").delete().eq("complaint_id", complaint_id).execute()
    await client.table("complaints").delete().eq("id", complaint_id).eq("school_id", school_id).execute()


# ---------------------------------------------------------------------------
# Helper: check complaint access
# ---------------------------------------------------------------------------

def _check_complaint_access(row: dict, user: dict) -> None:
    role = user.get("role", "")
    if _is_admin(user):
        return
    if role == "teacher":
        if row.get("submitted_by_user_id") != user["id"] and row.get("assigned_to_user_id") != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view this complaint")
        return
    if role in ("student", "parent"):
        if row.get("submitted_by_user_id") != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view this complaint")
        return


# ---------------------------------------------------------------------------
# Helper: convert DB row to ComplaintOut (strip internal info for students/parents)
# ---------------------------------------------------------------------------

def _row_to_complaint(row: dict, user: dict) -> ComplaintOut:
    role = user.get("role", "")
    # For students/parents, hide internal fields
    if role in ("student", "parent"):
        row = {**row, "resolution_notes": "", "assigned_to_user_id": None, "assigned_to_name": ""}
    return ComplaintOut(**row)


# ---------------------------------------------------------------------------
# Helper: log activity
# ---------------------------------------------------------------------------

async def _log_activity(
    school_id: str,
    complaint_id: str,
    action: str,
    description: str,
    user: dict,
    is_internal: bool = False,
) -> None:
    client = get_client()
    await client.table("complaint_activity").insert({
        "school_id": school_id,
        "complaint_id": complaint_id,
        "action": action,
        "description": description,
        "actor_user_id": user["id"],
        "actor_name": user.get("full_name", ""),
        "actor_role": user.get("role", ""),
        "is_internal": is_internal,
    }).execute()


# ---------------------------------------------------------------------------
# Behaviour — list
# ---------------------------------------------------------------------------

async def list_behaviour(
    school_id: str,
    user: dict,
    type_filter: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
) -> List[BehaviourRecordOut]:
    client = get_client()
    query = client.table("behaviour_records").select(_BEHAVIOUR_COLUMNS).eq("school_id", school_id)

    role = user.get("role", "")
    # Student/parent: only see their linked student's visible records
    if role in ("student", "parent"):
        linked_id = await _resolve_linked_student_id(school_id, user)
        if not linked_id:
            return []
        query = query.eq("student_id", linked_id).eq("is_visible_to_student", True)
    # Teacher: see records they created + records for students they teach (simplified: their own + all if admin)
    elif role == "teacher":
        query = query.or_(f"recorded_by_user_id.eq.{user['id']},is_visible_to_student.eq.true")
    # Admin: see all

    if type_filter:
        query = query.eq("type", type_filter)
    if category:
        query = query.eq("category", category)

    query = query.order("created_at", desc=True).limit(limit)
    res = await query.execute()
    rows = res.data or []

    if search:
        s = search.lower()
        rows = [r for r in rows if s in (r.get("student_name", "")).lower() or s in (r.get("description", "")).lower()]

    return [BehaviourRecordOut(**r) for r in rows]


# ---------------------------------------------------------------------------
# Behaviour — create (teacher/admin)
# ---------------------------------------------------------------------------

async def create_behaviour(school_id: str, user: dict, body: BehaviourRecordCreateIn) -> BehaviourRecordOut:
    if user.get("role") not in _STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only staff can create behaviour records")

    client = get_client()
    # Fetch student name if not provided
    student_name = body.student_name
    if not student_name and body.student_id:
        s_res = await client.table("students").select("full_name,class_name,section_name").eq("id", body.student_id).limit(1).execute()
        if s_res.data:
            student_name = s_res.data[0].get("full_name", "")
            if not body.class_name:
                body.class_name = s_res.data[0].get("class_name", "")
            if not body.section_name:
                body.section_name = s_res.data[0].get("section_name", "")

    row = {
        "school_id": school_id,
        "student_id": body.student_id,
        "student_name": student_name,
        "class_name": body.class_name,
        "section_name": body.section_name,
        "type": body.type,
        "category": body.category,
        "description": body.description,
        "severity": body.severity,
        "incident_date": body.incident_date.isoformat() if body.incident_date else None,
        "recorded_by_user_id": user["id"],
        "recorded_by_name": user.get("full_name", ""),
        "recorded_by_role": user.get("role", ""),
        "is_visible_to_student": body.is_visible_to_student,
    }
    res = await client.table("behaviour_records").insert(row).execute()
    created_id = res.data[0]["id"] if res.data else None

    out_row = await client.table("behaviour_records").select(_BEHAVIOUR_COLUMNS).eq("id", created_id).limit(1).execute()
    return BehaviourRecordOut(**out_row.data[0])


# ---------------------------------------------------------------------------
# Behaviour — update (creator or admin)
# ---------------------------------------------------------------------------

async def update_behaviour(school_id: str, record_id: str, user: dict, body: BehaviourRecordUpdateIn) -> BehaviourRecordOut:
    client = get_client()
    res = (
        await client.table("behaviour_records")
        .select(f"{_BEHAVIOUR_COLUMNS},recorded_by_user_id")
        .eq("school_id", school_id)
        .eq("id", record_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Behaviour record not found")
    row = res.data[0]

    is_creator = row.get("recorded_by_user_id") == user["id"]
    if not is_creator and not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to edit this record")

    update_data: dict = {}
    if body.type is not None:
        update_data["type"] = body.type
    if body.category is not None:
        update_data["category"] = body.category
    if body.description is not None:
        update_data["description"] = body.description
    if body.severity is not None:
        update_data["severity"] = body.severity
    if body.incident_date is not None:
        update_data["incident_date"] = body.incident_date.isoformat()
    if body.is_visible_to_student is not None:
        update_data["is_visible_to_student"] = body.is_visible_to_student

    if update_data:
        update_data["updated_at"] = datetime.utcnow().isoformat()
        await client.table("behaviour_records").update(update_data).eq("id", record_id).eq("school_id", school_id).execute()

    out_res = await client.table("behaviour_records").select(_BEHAVIOUR_COLUMNS).eq("id", record_id).limit(1).execute()
    return BehaviourRecordOut(**out_res.data[0])


# ---------------------------------------------------------------------------
# Behaviour — delete (creator or admin)
# ---------------------------------------------------------------------------

async def delete_behaviour(school_id: str, record_id: str, user: dict) -> None:
    client = get_client()
    res = (
        await client.table("behaviour_records")
        .select("recorded_by_user_id")
        .eq("school_id", school_id)
        .eq("id", record_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Behaviour record not found")
    row = res.data[0]
    is_creator = row.get("recorded_by_user_id") == user["id"]
    if not is_creator and not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to delete this record")

    await client.table("behaviour_records").delete().eq("id", record_id).eq("school_id", school_id).execute()


# ---------------------------------------------------------------------------
# Disciplinary actions
# ---------------------------------------------------------------------------

async def list_disciplinary(school_id: str, user: dict, student_id: Optional[str] = None) -> List[DisciplinaryActionOut]:
    client = get_client()
    query = client.table("disciplinary_actions").select(_DISCIPLINARY_COLUMNS).eq("school_id", school_id)

    role = user.get("role", "")
    if role in ("student", "parent"):
        linked = await _resolve_linked_student_id(school_id, user)
        if not linked:
            return []
        query = query.eq("student_id", linked)
    elif student_id:
        query = query.eq("student_id", student_id)

    query = query.order("created_at", desc=True).limit(50)
    res = await query.execute()
    return [DisciplinaryActionOut(**r) for r in (res.data or [])]


async def create_disciplinary(school_id: str, user: dict, body: DisciplinaryActionCreateIn) -> DisciplinaryActionOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can create disciplinary actions")

    client = get_client()
    student_name = body.student_name
    if not student_name and body.student_id:
        s_res = await client.table("students").select("full_name").eq("id", body.student_id).limit(1).execute()
        if s_res.data:
            student_name = s_res.data[0].get("full_name", "")

    row = {
        "school_id": school_id,
        "student_id": body.student_id,
        "student_name": student_name,
        "behaviour_record_id": body.behaviour_record_id,
        "action_type": body.action_type,
        "notes": body.notes,
        "status": body.status,
        "action_date": body.action_date.isoformat() if body.action_date else None,
        "created_by_user_id": user["id"],
        "created_by_name": user.get("full_name", ""),
    }
    res = await client.table("disciplinary_actions").insert(row).execute()
    created_id = res.data[0]["id"] if res.data else None
    out_res = await client.table("disciplinary_actions").select(_DISCIPLINARY_COLUMNS).eq("id", created_id).limit(1).execute()
    return DisciplinaryActionOut(**out_res.data[0])


# ---------------------------------------------------------------------------
# Analytics (admin)
# ---------------------------------------------------------------------------

async def get_analytics(school_id: str, user: dict) -> ComplaintAnalyticsOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can view analytics")

    client = get_client()

    # Complaint counts by status
    c_res = await client.table("complaints").select("status,severity,category").eq("school_id", school_id).execute()
    complaints = c_res.data or []

    by_status: Dict[str, int] = {}
    by_severity: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    high_priority = 0
    for c in complaints:
        s = c.get("status", "pending")
        by_status[s] = by_status.get(s, 0) + 1
        sev = c.get("severity", "low")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        if sev in ("high", "critical"):
            high_priority += 1
        cat = c.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + 1

    # Behaviour counts
    b_res = await client.table("behaviour_records").select("type").eq("school_id", school_id).execute()
    behaviours = b_res.data or []
    positive = sum(1 for b in behaviours if b.get("type") == "positive")
    negative = sum(1 for b in behaviours if b.get("type") == "negative")

    return ComplaintAnalyticsOut(
        total_complaints=len(complaints),
        pending=by_status.get("pending", 0),
        under_review=by_status.get("under_review", 0),
        resolved=by_status.get("resolved", 0),
        rejected=by_status.get("rejected", 0),
        high_priority=high_priority,
        total_behaviour=len(behaviours),
        positive_behaviour=positive,
        negative_behaviour=negative,
        by_category=by_category,
        by_severity=by_severity,
        by_status=by_status,
    )

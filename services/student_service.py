"""Student CRUD with user account provisioning."""
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.people import (
    CredentialsOut,
    StudentCreateIn,
    StudentCreateOut,
    StudentDocumentItem,
    StudentMedicalIn,
    StudentMedicalOut,
    StudentMedicalVisitOut,
    StudentOut,
    StudentUpdateIn,
)
from utils.codes import generate_admission_no, generate_temp_password, generate_user_code, normalize_admission_no
from utils.security import hash_password

logger = logging.getLogger("eduspace.students")


def _documents_payload(documents: Optional[List[StudentDocumentItem]]) -> list:
    return [
        {"document_url": doc.document_url, "document_name": doc.document_name}
        for doc in (documents or [])
    ]


def _documents_from_profile(profile: dict) -> list:
    raw = profile.get("documents")
    if isinstance(raw, list) and raw:
        return raw
    if profile.get("document_url"):
        return [
            {
                "document_url": profile["document_url"],
                "document_name": profile.get("document_name") or "document",
            }
        ]
    return []


async def _max_admission_sequence(school_id: str) -> int:
    """Highest numeric admission number already used in this school."""
    client = get_client()
    max_num = 0
    for table in ("students", "users"):
        res = (
            await client.table(table)
            .select("admission_no")
            .eq("school_id", school_id)
            .execute()
        )
        for row in res.data or []:
            an = (row.get("admission_no") or "").strip()
            if an.isdigit():
                max_num = max(max_num, int(an))
    return max_num


async def _admission_taken(school_id: str, admission_no: str, *, exclude_user_id: Optional[str] = None) -> bool:
    client = get_client()
    student_res = (
        await client.table("students")
        .select("id,user_id")
        .eq("school_id", school_id)
        .eq("admission_no", admission_no)
        .limit(1)
        .execute()
    )
    if student_res.data:
        if not (exclude_user_id and student_res.data[0].get("user_id") == exclude_user_id):
            return True

    user_res = (
        await client.table("users")
        .select("id")
        .eq("school_id", school_id)
        .eq("admission_no", admission_no)
        .limit(1)
        .execute()
    )
    if user_res.data:
        if not (exclude_user_id and user_res.data[0].get("id") == exclude_user_id):
            return True
    return False


async def _next_student_codes(school_id: str) -> tuple[str, str, int]:
    client = get_client()
    res = (
        await client.table("users")
        .select("user_code")
        .eq("school_id", school_id)
        .eq("role", "student")
        .execute()
    )
    stu_nums = []
    for row in res.data or []:
        uc = row.get("user_code") or ""
        try:
            if uc.startswith("STU"):
                stu_nums.append(int(uc[3:]))
        except ValueError:
            pass
    user_count = max(stu_nums) if stu_nums else 0
    adm_count = await _max_admission_sequence(school_id)
    user_code = generate_user_code("student", user_count)
    admission_no = generate_admission_no(adm_count)
    return user_code, admission_no, adm_count


async def _resolve_class_section(school_id: str, class_id: Optional[str], section_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not class_id:
        return None, None
    client = get_client()
    cls = await client.table("classes").select("name").eq("id", class_id).eq("school_id", school_id).limit(1).execute()
    class_name = cls.data[0]["name"] if cls.data else None
    section_name = None
    if section_id:
        sec = await client.table("sections").select("name").eq("id", section_id).eq("school_id", school_id).limit(1).execute()
        section_name = sec.data[0]["name"] if sec.data else None
    return class_name, section_name


def _build_student_out(user: dict, profile: dict, class_name: Optional[str] = None, section_name: Optional[str] = None) -> StudentOut:
    return StudentOut(
        id=profile["id"],
        user_id=user["id"],
        full_name=user["full_name"],
        email=user.get("email"),
        admission_no=profile.get("admission_no") or user.get("admission_no"),
        user_code=user.get("user_code"),
        gender=profile.get("gender") or user.get("gender"),
        dob=profile.get("dob") or user.get("dob"),
        father_name=profile.get("father_name"),
        mother_name=profile.get("mother_name"),
        guardian_mobile=profile.get("guardian_mobile") or user.get("mobile"),
        alternate_mobile=profile.get("alternate_mobile"),
        address=profile.get("address") or user.get("address"),
        transport=profile.get("transport"),
        class_id=profile.get("class_id"),
        section_id=profile.get("section_id"),
        class_name=class_name,
        section_name=section_name,
        roll_no=profile.get("roll_no"),
        admission_date=profile.get("admission_date"),
        photo_url=profile.get("photo_url") or user.get("photo_url"),
        is_active=user.get("is_active", True),
        login_password=user.get("login_password"),
        pen_number=profile.get("pen_number"),
        aadhar_number=profile.get("aadhar_number"),
        category=profile.get("category"),
        documents=_documents_from_profile(profile),
        document_url=profile.get("document_url"),
        document_name=profile.get("document_name"),
        approval_status=profile.get("approval_status") or "approved",
    )


async def list_students(
    school_id: str,
    class_id: Optional[str] = None,
    section_id: Optional[str] = None,
    search: Optional[str] = None,
    *,
    approval_status: Optional[str] = "approved",
) -> List[StudentOut]:
    client = get_client()
    query = client.table("students").select("*").eq("school_id", school_id)
    if class_id:
        query = query.eq("class_id", class_id)
    if section_id:
        query = query.eq("section_id", section_id)
    res = await query.order("created_at", desc=True).limit(500).execute()
    if not res.data:
        return []
    user_ids = [p["user_id"] for p in res.data if p.get("user_id")]
    users_res = await client.table("users").select(
        "id,email,full_name,mobile,user_code,admission_no,is_active,gender,dob,address,photo_url,login_password"
    ).in_("id", user_ids).execute()
    users_map = {u["id"]: u for u in (users_res.data or [])}

    # Batch-resolve class and section names to avoid N+1 queries.
    # Collect unique class_ids and section_ids, then fetch in 2 queries.
    class_ids = {p.get("class_id") for p in res.data if p.get("class_id")}
    section_ids = {p.get("section_id") for p in res.data if p.get("section_id")}
    class_names_map: dict = {}
    section_names_map: dict = {}
    if class_ids:
        cls_res = await client.table("classes").select("id,name").in_("id", list(class_ids)).execute()
        class_names_map = {c["id"]: c["name"] for c in (cls_res.data or [])}
    if section_ids:
        sec_res = await client.table("sections").select("id,name").in_("id", list(section_ids)).execute()
        section_names_map = {s["id"]: s["name"] for s in (sec_res.data or [])}

    out = []
    for p in res.data:
        user = users_map.get(p.get("user_id"))
        if not user:
            continue
        # Rows created before approval_status column may omit it; treat as approved.
        row_status = p.get("approval_status") or "approved"
        if approval_status and row_status != approval_status:
            continue
        if search:
            q = search.lower()
            hay = f"{user['full_name']} {p.get('admission_no','')} {p.get('roll_no','')}".lower()
            if q not in hay:
                continue
        cn = class_names_map.get(p.get("class_id"))
        sn = section_names_map.get(p.get("section_id"))
        out.append(_build_student_out(user, p, cn, sn))
    return sorted(out, key=lambda s: (s.class_name or "", s.roll_no or "", s.full_name.lower()))


async def get_student(school_id: str, student_id: str) -> StudentOut:
    client = get_client()
    res = await client.table("students").select("*").eq("school_id", school_id).eq("id", student_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    profile = res.data[0]
    user_res = await client.table("users").select(
        "id,email,full_name,mobile,user_code,admission_no,is_active,gender,dob,address,photo_url,login_password"
    ).eq("id", profile["user_id"]).limit(1).execute()
    if not user_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student user not found")
    cn, sn = await _resolve_class_section(school_id, profile.get("class_id"), profile.get("section_id"))
    return _build_student_out(user_res.data[0], profile, cn, sn)


async def get_student_by_user_id(school_id: str, user_id: str) -> StudentOut:
    client = get_client()
    res = (
        await client.table("students")
        .select("*")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student profile not found")
    profile = res.data[0]
    user_res = await client.table("users").select(
        "id,email,full_name,mobile,user_code,admission_no,is_active,gender,dob,address,photo_url,login_password"
    ).eq("id", profile["user_id"]).limit(1).execute()
    if not user_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student user not found")
    cn, sn = await _resolve_class_section(school_id, profile.get("class_id"), profile.get("section_id"))
    return _build_student_out(user_res.data[0], profile, cn, sn)


async def create_student(
    school_id: str,
    body: StudentCreateIn,
    *,
    pending_approval: bool = False,
    requested_by_user_id: Optional[str] = None,
) -> StudentCreateOut:
    client = get_client()
    
    # Check school's student_approval_required setting.
    # Wrapped in try/except so a missing column (migration 054) doesn't
    # break student creation — defaults to True (safer) if query fails.
    school_approval_required = True
    try:
        school_res = (
            await client.table("schools")
            .select("student_approval_required")
            .eq("id", school_id)
            .limit(1)
            .execute()
        )
        if school_res.data:
            school_approval_required = bool(school_res.data[0].get("student_approval_required", True))
    except Exception:
        logger.warning("student_approval_required column missing — run migration 054_student_settings.sql")
    
    # If school doesn't require approval, override pending_approval to false
    if not school_approval_required:
        pending_approval = False
        requested_by_user_id = None
    
    user_code, default_adm, _ = await _next_student_codes(school_id)
    if body.admission_no and body.admission_no.strip():
        admission_no = normalize_admission_no(body.admission_no)
    else:
        admission_no = default_adm

    if await _admission_taken(school_id, admission_no):
        raise HTTPException(status.HTTP_409_CONFLICT, "Admission number already used in this school")

    # Duplicate check: same full_name + father_name + guardian_mobile
    dup_res = (
        await client.table("students")
        .select("id,user_id")
        .eq("school_id", school_id)
        .ilike("father_name", body.father_name or "")
        .eq("guardian_mobile", body.guardian_mobile or "")
        .limit(5)
        .execute()
    )
    if dup_res.data:
        for row in dup_res.data:
            u_res = (
                await client.table("users")
                .select("full_name")
                .eq("id", row.get("user_id"))
                .ilike("full_name", body.full_name)
                .limit(1)
                .execute()
            )
            if u_res.data:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "A student with the same name, parent name and contact already exists",
                )

    email = (body.email or f"student_{admission_no}_{school_id[:8]}@eduspace.local").lower()

    if body.email:
        existing = (
            await client.table("users")
            .select("id")
            .eq("school_id", school_id)
            .eq("email", email)
            .limit(1)
            .execute()
        )
        if existing.data:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    temp_password = generate_temp_password()
    approval_status = "pending" if pending_approval else "approved"

    user_row = {
        "school_id": school_id,
        "email": email,
        "full_name": body.full_name,
        "role": "student",
        "user_code": user_code,
        "admission_no": admission_no,
        "mobile": body.guardian_mobile,
        "gender": body.gender,
        "dob": body.dob.isoformat() if body.dob else None,
        "address": body.address,
        "photo_url": body.photo_url,
        "password_hash": hash_password(temp_password),
        "login_password": temp_password,
        "must_change_password": True,
        "is_active": not pending_approval,
    }
    try:
        user_ins = await client.table("users").insert(user_row).execute()
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        # Try removing optional columns that may be missing from older schemas
        optional_user_cols = ["login_password", "photo_url", "gender", "dob", "mobile", "address"]
        retry_user = {**user_row}
        retried = False
        for col in optional_user_cols:
            if col in retry_user and col in message:
                retry_user.pop(col, None)
                retried = True
        if retried:
            try:
                user_ins = await client.table("users").insert(retry_user).execute()
            except Exception as retry_exc:  # noqa: BLE001
                logger.error("Student user creation failed after retry: %s", retry_exc)
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create student user")
        else:
            logger.error("Student user creation failed: %s", exc)
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create student user")
    if not user_ins.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create student user")
    user = user_ins.data[0]

    student_row = {
        "school_id": school_id,
        "user_id": user["id"],
        "admission_no": admission_no,
        "class_id": body.class_id,
        "section_id": body.section_id,
        "roll_no": body.roll_no,
        "gender": body.gender,
        "dob": body.dob.isoformat() if body.dob else None,
        "father_name": body.father_name,
        "mother_name": body.mother_name,
        "guardian_mobile": body.guardian_mobile,
        "alternate_mobile": body.alternate_mobile,
        "address": body.address,
        "transport": (body.transport or "").strip() or None,
        "photo_url": body.photo_url,
        "admission_date": body.admission_date.isoformat() if body.admission_date else None,
        "pen_number": body.pen_number,
        "aadhar_number": body.aadhar_number,
        "category": body.category,
        "documents": _documents_payload(body.documents),
        "document_url": body.documents[0].document_url if body.documents else None,
        "document_name": body.documents[0].document_name if body.documents else None,
        "approval_status": approval_status,
        "requested_by_user_id": requested_by_user_id,
    }
    try:
        s_ins = await client.table("students").insert(student_row).execute()
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        missing_approval = "approval_status" in message or "requested_by_user_id" in message
        if pending_approval and missing_approval:
            await client.table("users").delete().eq("id", user["id"]).execute()
            logger.error("Student request requires migration 047_student_approval_status.sql: %s", exc)
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Student requests need database update. Run migrations/047_student_approval_status.sql",
            )
        if missing_approval and not pending_approval:
            student_row.pop("approval_status", None)
            student_row.pop("requested_by_user_id", None)
            try:
                s_ins = await client.table("students").insert(student_row).execute()
            except Exception as retry_exc:  # noqa: BLE001
                await client.table("users").delete().eq("id", user["id"]).execute()
                logger.error("Student profile creation failed: %s", retry_exc)
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create student profile")
        else:
            # Try progressively removing optional columns that may be missing
            # from older database schemas (migrations 007-054).
            optional_cols = [
                "transport", "pen_number", "aadhar_number", "category",
                "alternate_mobile", "documents", "document_url", "document_name",
                "approval_status", "requested_by_user_id",
            ]
            retry_row = {**student_row}
            retried = False
            for col in optional_cols:
                if col in retry_row and col in message:
                    retry_row.pop(col, None)
                    retried = True
            if retried:
                try:
                    s_ins = await client.table("students").insert(retry_row).execute()
                except Exception as retry_exc:  # noqa: BLE001
                    await client.table("users").delete().eq("id", user["id"]).execute()
                    logger.error("Student profile creation failed after retry: %s", retry_exc)
                    raise HTTPException(
                        status.HTTP_500_INTERNAL_SERVER_ERROR,
                        "Failed to create student profile. Database may need migrations.",
                    )
            else:
                await client.table("users").delete().eq("id", user["id"]).execute()
                logger.error("Student profile creation failed: %s", exc)
                raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create student profile")

    if not s_ins.data:
        await client.table("users").delete().eq("id", user["id"]).execute()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create student profile")

    cn, sn = await _resolve_class_section(school_id, body.class_id, body.section_id)
    student = _build_student_out(user, s_ins.data[0], cn, sn)
    return StudentCreateOut(
        student=student,
        credentials=CredentialsOut(user_code=admission_no, password=temp_password),
        pending_approval=pending_approval,
    )


async def approve_student_request(school_id: str, student_id: str) -> StudentOut:
    client = get_client()
    profile_res = (
        await client.table("students")
        .select("*")
        .eq("school_id", school_id)
        .eq("id", student_id)
        .limit(1)
        .execute()
    )
    if not profile_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student request not found")
    profile = profile_res.data[0]
    if profile.get("approval_status") != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student is not pending approval")

    await client.table("students").update({"approval_status": "approved"}).eq("id", student_id).execute()
    await client.table("users").update({"is_active": True}).eq("id", profile["user_id"]).execute()
    return await get_student(school_id, student_id)


async def reject_student_request(school_id: str, student_id: str) -> None:
    client = get_client()
    profile_res = (
        await client.table("students")
        .select("id,user_id,approval_status")
        .eq("school_id", school_id)
        .eq("id", student_id)
        .limit(1)
        .execute()
    )
    if not profile_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student request not found")
    profile = profile_res.data[0]
    if profile.get("approval_status") != "pending":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student is not pending approval")
    user_id = profile.get("user_id")
    await client.table("students").delete().eq("id", student_id).execute()
    if user_id:
        await client.table("users").delete().eq("id", user_id).execute()


async def update_student_self(
    school_id: str,
    user_id: str,
    body: StudentUpdateIn,
) -> StudentOut:
    """Students may update their own contact details only."""
    profile = await get_student_by_user_id(school_id, user_id)
    personal = StudentUpdateIn(
        email=body.email,
        guardian_mobile=body.guardian_mobile,
        alternate_mobile=body.alternate_mobile,
        address=body.address,
        photo_url=body.photo_url,
    )
    return await update_student(school_id, profile.id, personal)


async def update_student(school_id: str, student_id: str, body: StudentUpdateIn) -> StudentOut:
    client = get_client()
    profile_res = await client.table("students").select("*").eq("school_id", school_id).eq("id", student_id).limit(1).execute()
    if not profile_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    profile = profile_res.data[0]

    user_updates = {}
    for field in ("full_name", "gender", "dob", "address", "photo_url"):
        val = getattr(body, field, None)
        if val is not None:
            user_updates[field] = val.isoformat() if field == "dob" and val else val
    if body.email:
        user_updates["email"] = body.email.lower()
    if body.guardian_mobile:
        user_updates["mobile"] = body.guardian_mobile
    if user_updates:
        await client.table("users").update(user_updates).eq("id", profile["user_id"]).execute()

    profile_updates = {}
    for field in (
        "gender", "dob", "father_name", "mother_name", "guardian_mobile",
        "address", "photo_url", "class_id", "section_id", "roll_no", "admission_date",
        "pen_number", "aadhar_number", "category",
    ):
        val = getattr(body, field, None)
        if val is not None:
            profile_updates[field] = val.isoformat() if field in ("dob", "admission_date") and val else val
    if "alternate_mobile" in body.model_fields_set:
        profile_updates["alternate_mobile"] = body.alternate_mobile
    if "transport" in body.model_fields_set:
        profile_updates["transport"] = (body.transport or "").strip() or None
    if "aadhar_number" in body.model_fields_set and body.aadhar_number is None:
        profile_updates["aadhar_number"] = None
    if body.documents is not None:
        profile_updates["documents"] = _documents_payload(body.documents)
        profile_updates["document_url"] = body.documents[0].document_url if body.documents else None
        profile_updates["document_name"] = body.documents[0].document_name if body.documents else None
    if profile_updates:
        await client.table("students").update(profile_updates).eq("id", student_id).execute()

    if body.full_name:
        await client.table("users").update({"full_name": body.full_name}).eq("id", profile["user_id"]).execute()

    return await get_student(school_id, student_id)


async def delete_student(school_id: str, student_id: str) -> None:
    client = get_client()
    res = await client.table("students").select("user_id").eq("school_id", school_id).eq("id", student_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    user_id = res.data[0]["user_id"]
    await client.table("students").delete().eq("id", student_id).execute()
    if user_id:
        await client.table("users").delete().eq("id", user_id).execute()


STUDENT_MEDICAL_FIELDS = (
    "height",
    "weight",
    "blood_group",
    "allergies",
    "conditions",
    "medications",
    "emergency_name",
    "emergency_relation",
    "emergency_mobile",
    "notes",
)

STUDENT_VISITS_TABLE = "teacher_medical_visits"


async def _own_student_profile_row(school_id: str, user_id: str) -> tuple[dict, dict]:
    client = get_client()
    res = (
        await client.table("students")
        .select("*")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student profile not found")
    profile = res.data[0]
    user_res = (
        await client.table("users")
        .select("id,full_name,gender,dob")
        .eq("id", profile["user_id"])
        .limit(1)
        .execute()
    )
    return profile, (user_res.data[0] if user_res.data else {})


def _build_student_medical_out(profile: dict, user: dict) -> StudentMedicalOut:
    return StudentMedicalOut(
        student_id=profile["id"],
        full_name=user.get("full_name"),
        gender=profile.get("gender") or user.get("gender"),
        dob=profile.get("dob") or user.get("dob"),
        updated_at=profile.get("medical_updated_at"),
        **{field: profile.get(f"medical_{field}") for field in STUDENT_MEDICAL_FIELDS},
    )


async def get_my_medical(school_id: str, user_id: str) -> StudentMedicalOut:
    profile, user = await _own_student_profile_row(school_id, user_id)
    return _build_student_medical_out(profile, user)


async def update_my_medical(
    school_id: str,
    user_id: str,
    body: StudentMedicalIn,
) -> StudentMedicalOut:
    profile, _ = await _own_student_profile_row(school_id, user_id)
    updates: dict = {}
    for field in STUDENT_MEDICAL_FIELDS:
        value = getattr(body, field, None)
        if value is None:
            continue
        cleaned = value.strip()
        updates[f"medical_{field}"] = cleaned or None
    updates["medical_updated_at"] = datetime.now(timezone.utc).isoformat()
    client = get_client()
    await client.table("students").update(updates).eq("id", profile["id"]).execute()
    return await get_my_medical(school_id, user_id)


def _build_student_visit_out(row: dict) -> StudentMedicalVisitOut:
    return StudentMedicalVisitOut(
        id=row["id"],
        visit_date=row["visit_date"],
        visit_time=row.get("visit_time") or "",
        issue=row.get("issue") or "",
        treatment=row.get("treatment") or "",
        prescription=row.get("prescription") or "",
        attended_by=row.get("attended_by") or "",
        created_at=row.get("created_at"),
    )


async def list_my_medical_visits(school_id: str, user_id: str) -> List[StudentMedicalVisitOut]:
    """Visits the school doctor logged against this student.

    Visits are stored in the shared teacher_medical_visits table (which also
    holds student visits via person_role), keyed by user_id.
    """
    client = get_client()
    res = (
        await client.table(STUDENT_VISITS_TABLE)
        .select("*")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .order("visit_date", desc=True)
        .limit(200)
        .execute()
    )
    return [_build_student_visit_out(row) for row in (res.data or [])]

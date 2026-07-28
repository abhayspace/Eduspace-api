"""Teacher CRUD with user account provisioning."""
import logging
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.people import TeacherCreateIn, TeacherCreateOut, TeacherOut, TeacherUpdateIn, CredentialsOut, StudentDocumentItem
from utils.codes import generate_employee_no, generate_temp_password, generate_user_code
from utils.security import hash_password

logger = logging.getLogger("eduspace.teachers")

STAFF_ROLES = {"teacher"}


def _documents_payload(documents: Optional[List[StudentDocumentItem]]) -> list:
    return [
        {"document_url": doc.document_url, "document_name": doc.document_name}
        for doc in (documents or [])
    ]


def _documents_from_profile(profile: dict) -> list:
    raw = profile.get("documents")
    if isinstance(raw, list) and raw:
        return [
            StudentDocumentItem(
                document_url=item.get("document_url", ""),
                document_name=item.get("document_name", "document"),
            )
            for item in raw
            if item.get("document_url")
        ]
    if profile.get("document_url"):
        return [
            StudentDocumentItem(
                document_url=profile["document_url"],
                document_name=profile.get("document_name") or "document",
            )
        ]
    return []


async def _next_code(school_id: str, role: str, field: str = "user_code") -> tuple[str, int]:
    client = get_client()
    prefix_map = {
        "teacher": "TCH",
    }
    prefix = prefix_map.get(role, "USR")
    res = (
        await client.table("users")
        .select(field)
        .eq("school_id", school_id)
        .eq("role", role)
        .like(field, f"{prefix}%")
        .execute()
    )
    nums = []
    for row in res.data or []:
        val = row.get(field) or ""
        try:
            nums.append(int(val[len(prefix):]))
        except (ValueError, IndexError):
            pass
    count = max(nums) if nums else 0
    return generate_user_code(role, count), count


async def _next_employee_no(school_id: str, role: str) -> str:
    client = get_client()
    prefix = "EMP-TCH"
    res = (
        await client.table("teachers")
        .select("employee_no")
        .eq("school_id", school_id)
        .like("employee_no", f"{prefix}%")
        .execute()
    )
    nums = []
    for row in res.data or []:
        val = row.get("employee_no") or ""
        try:
            nums.append(int(val.split("-")[-1]))
        except (ValueError, IndexError):
            pass
    count = max(nums) if nums else 0
    return generate_employee_no(role, count)


async def _validate_class_teacher(
    school_id: str,
    is_class_teacher: bool,
    class_id: Optional[str],
    section_id: Optional[str],
    exclude_teacher_id: Optional[str] = None,
) -> None:
    if not is_class_teacher:
        return
    if not class_id or not section_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Class and section required for class teacher")
    client = get_client()
    query = (
        client.table("teachers")
        .select("id")
        .eq("school_id", school_id)
        .eq("is_class_teacher", True)
        .eq("class_teacher_class_id", class_id)
        .eq("class_teacher_section_id", section_id)
    )
    res = await query.execute()
    for row in res.data or []:
        if exclude_teacher_id and row["id"] == exclude_teacher_id:
            continue
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A class teacher is already assigned to this class-section",
        )


async def _resolve_class_names(school_id: str, class_id: Optional[str], section_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
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


async def get_user_class_teacher_info(school_id: str, user_id: str) -> dict:
    """Return class-teacher fields for auth /me enrichment."""
    client = get_client()
    res = (
        await client.table("teachers")
        .select("id,is_class_teacher,class_teacher_class_id,class_teacher_section_id,gender")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {
            "teacher_id": None,
            "is_class_teacher": False,
            "class_teacher_class_id": None,
            "class_teacher_section_id": None,
            "class_teacher_class_name": None,
            "class_teacher_section_name": None,
        }
    profile = res.data[0]
    class_name, section_name = await _resolve_class_names(
        school_id,
        profile.get("class_teacher_class_id"),
        profile.get("class_teacher_section_id"),
    )
    out = {
        "teacher_id": profile.get("id"),
        "is_class_teacher": bool(profile.get("is_class_teacher")),
        "class_teacher_class_id": profile.get("class_teacher_class_id"),
        "class_teacher_section_id": profile.get("class_teacher_section_id"),
        "class_teacher_class_name": class_name,
        "class_teacher_section_name": section_name,
    }
    if profile.get("gender"):
        out["gender"] = profile.get("gender")
    return out


def _build_teacher_out(user: dict, profile: dict, class_name: Optional[str] = None, section_name: Optional[str] = None) -> TeacherOut:
    return TeacherOut(
        id=profile["id"],
        user_id=user["id"],
        full_name=user["full_name"],
        email=user["email"],
        mobile=user.get("mobile"),
        user_code=user.get("user_code"),
        employee_no=profile.get("employee_no"),
        gender=profile.get("gender") or user.get("gender"),
        dob=profile.get("dob") or user.get("dob"),
        address=profile.get("address") or user.get("address"),
        qualification=profile.get("qualification"),
        experience_years=profile.get("experience_years"),
        joining_date=profile.get("joining_date"),
        department=profile.get("department"),
        photo_url=profile.get("photo_url") or user.get("photo_url"),
        subjects=profile.get("subjects") or [],
        classes_teaching=profile.get("classes_teaching") or [],
        documents=_documents_from_profile(profile),
        document_url=profile.get("document_url"),
        document_name=profile.get("document_name"),
        is_class_teacher=profile.get("is_class_teacher", False),
        class_teacher_class_id=profile.get("class_teacher_class_id"),
        class_teacher_section_id=profile.get("class_teacher_section_id"),
        class_teacher_class_name=class_name,
        class_teacher_section_name=section_name,
        is_active=user.get("is_active", True),
        login_password=user.get("login_password"),
    )


async def list_teachers(school_id: str) -> List[TeacherOut]:
    client = get_client()
    profiles = (
        await client.table("teachers")
        .select("*")
        .eq("school_id", school_id)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    if not profiles.data:
        return []
    user_ids = [p["user_id"] for p in profiles.data if p.get("user_id")]
    users_res = await client.table("users").select("id,email,full_name,mobile,user_code,is_active,gender,dob,address,photo_url,login_password").in_("id", user_ids).execute()
    users_map = {u["id"]: u for u in (users_res.data or [])}
    out = []
    for p in profiles.data:
        user = users_map.get(p.get("user_id"))
        if not user:
            continue
        cn, sn = await _resolve_class_names(school_id, p.get("class_teacher_class_id"), p.get("class_teacher_section_id"))
        out.append(_build_teacher_out(user, p, cn, sn))
    return sorted(out, key=lambda t: t.full_name.lower())


async def get_teacher(school_id: str, teacher_id: str) -> TeacherOut:
    client = get_client()
    res = await client.table("teachers").select("*").eq("school_id", school_id).eq("id", teacher_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
    profile = res.data[0]
    user_res = await client.table("users").select("id,email,full_name,mobile,user_code,is_active,gender,dob,address,photo_url,login_password").eq("id", profile["user_id"]).limit(1).execute()
    if not user_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher user not found")
    cn, sn = await _resolve_class_names(school_id, profile.get("class_teacher_class_id"), profile.get("class_teacher_section_id"))
    return _build_teacher_out(user_res.data[0], profile, cn, sn)


async def get_teacher_by_user_id(school_id: str, user_id: str) -> TeacherOut:
    client = get_client()
    res = (
        await client.table("teachers")
        .select("*")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher profile not found")
    return await get_teacher(school_id, res.data[0]["id"])


async def update_teacher_self(
    school_id: str,
    user_id: str,
    body: TeacherUpdateIn,
) -> TeacherOut:
    """Teachers may update their own personal contact details only."""
    profile = await get_teacher_by_user_id(school_id, user_id)
    personal = TeacherUpdateIn(
        full_name=body.full_name,
        gender=body.gender,
        dob=body.dob,
        email=body.email,
        mobile=body.mobile,
        address=body.address,
        qualification=body.qualification,
        experience_years=body.experience_years,
        photo_url=body.photo_url,
    )
    return await update_teacher(school_id, profile.id, personal)


async def create_teacher(school_id: str, body: TeacherCreateIn) -> TeacherCreateOut:
    client = get_client()
    email = body.email.lower()

    existing = (
        await client.table("users")
        .select("id,role,is_active")
        .eq("school_id", school_id)
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if existing.data:
        existing_user = existing.data[0]
        teacher_link = (
            await client.table("teachers")
            .select("id")
            .eq("school_id", school_id)
            .eq("user_id", existing_user["id"])
            .limit(1)
            .execute()
        )
        if teacher_link.data:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Email {email} is already used by a teacher. Use a different email, or edit the existing teacher.",
            )
        # Leftover user row with no teacher profile (failed earlier create).
        if existing_user.get("role") == "teacher":
            await client.table("users").delete().eq("id", existing_user["id"]).execute()
        else:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Email {email} is already registered for another account. Use a different email.",
            )

    await _validate_class_teacher(
        school_id, body.is_class_teacher, body.class_teacher_class_id, body.class_teacher_section_id
    )

    user_code, _ = await _next_code(school_id, "teacher")
    employee_no = await _next_employee_no(school_id, "teacher")
    temp_password = generate_temp_password()

    user_row = {
        "school_id": school_id,
        "email": email,
        "full_name": body.full_name,
        "role": "teacher",
        "user_code": user_code,
        "mobile": body.mobile,
        "gender": body.gender,
        "dob": body.dob.isoformat() if body.dob else None,
        "address": body.address,
        "photo_url": body.photo_url,
        "password_hash": hash_password(temp_password),
        "login_password": temp_password,
        "must_change_password": True,
        "is_active": True,
    }
    user_ins = await client.table("users").insert(user_row).execute()
    if not user_ins.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create teacher user")
    user = user_ins.data[0]

    teacher_row = {
        "school_id": school_id,
        "user_id": user["id"],
        "employee_no": employee_no,
        "department": body.department,
        "gender": body.gender,
        "qualification": body.qualification,
        "experience_years": body.experience_years,
        "joining_date": body.joining_date.isoformat() if body.joining_date else None,
        "photo_url": body.photo_url,
        "subjects": body.subjects,
        "classes_teaching": body.classes_teaching,
        "documents": _documents_payload(body.documents),
        "document_url": body.documents[0].document_url if body.documents else None,
        "document_name": body.documents[0].document_name if body.documents else None,
        "is_class_teacher": body.is_class_teacher,
        "class_teacher_class_id": body.class_teacher_class_id,
        "class_teacher_section_id": body.class_teacher_section_id,
    }
    try:
        t_ins = await client.table("teachers").insert(teacher_row).execute()
    except Exception as exc:  # noqa: BLE001
        await client.table("users").delete().eq("id", user["id"]).execute()
        logger.error("Teacher profile creation failed: %s", exc)
        if "uq_class_teacher_assignment" in str(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, "A class teacher is already assigned to this class-section")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create teacher profile")

    if not t_ins.data:
        await client.table("users").delete().eq("id", user["id"]).execute()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create teacher profile")

    cn, sn = await _resolve_class_names(school_id, body.class_teacher_class_id, body.class_teacher_section_id)
    teacher = _build_teacher_out(user, t_ins.data[0], cn, sn)
    return TeacherCreateOut(
        teacher=teacher,
        credentials=CredentialsOut(user_code=user_code, password=temp_password),
    )


async def update_teacher(school_id: str, teacher_id: str, body: TeacherUpdateIn) -> TeacherOut:
    client = get_client()
    profile_res = await client.table("teachers").select("*").eq("school_id", school_id).eq("id", teacher_id).limit(1).execute()
    if not profile_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
    profile = profile_res.data[0]

    is_ct = body.is_class_teacher if body.is_class_teacher is not None else profile.get("is_class_teacher", False)
    if body.is_class_teacher is False:
        ct_class = None
        ct_section = None
    else:
        ct_class = (
            body.class_teacher_class_id
            if body.class_teacher_class_id is not None
            else profile.get("class_teacher_class_id")
        )
        ct_section = (
            body.class_teacher_section_id
            if body.class_teacher_section_id is not None
            else profile.get("class_teacher_section_id")
        )
    await _validate_class_teacher(school_id, is_ct, ct_class, ct_section, exclude_teacher_id=teacher_id)

    user_updates = {}
    for field in ("full_name", "gender", "dob", "address", "photo_url", "mobile"):
        val = getattr(body, field, None)
        if val is not None:
            user_updates[field] = val.isoformat() if field == "dob" and val else val
    if body.email:
        user_updates["email"] = body.email.lower()
    if user_updates:
        await client.table("users").update(user_updates).eq("id", profile["user_id"]).execute()

    profile_updates = {}
    for field in (
        "gender", "qualification", "experience_years", "joining_date", "department",
        "photo_url", "subjects", "classes_teaching", "is_class_teacher",
        "class_teacher_class_id", "class_teacher_section_id",
    ):
        val = getattr(body, field, None)
        if val is not None:
            profile_updates[field] = val.isoformat() if field == "joining_date" and val else val
    if body.is_class_teacher is False:
        profile_updates["is_class_teacher"] = False
        profile_updates["class_teacher_class_id"] = None
        profile_updates["class_teacher_section_id"] = None
    elif body.is_class_teacher is True:
        profile_updates["is_class_teacher"] = True
        profile_updates["class_teacher_class_id"] = ct_class
        profile_updates["class_teacher_section_id"] = ct_section
    if body.documents is not None:
        profile_updates["documents"] = _documents_payload(body.documents)
        profile_updates["document_url"] = body.documents[0].document_url if body.documents else None
        profile_updates["document_name"] = body.documents[0].document_name if body.documents else None
    if profile_updates:
        try:
            await client.table("teachers").update(profile_updates).eq("id", teacher_id).execute()
        except Exception as exc:  # noqa: BLE001
            if "uq_class_teacher_assignment" in str(exc):
                raise HTTPException(status.HTTP_409_CONFLICT, "A class teacher is already assigned to this class-section")
            raise

    return await get_teacher(school_id, teacher_id)


async def delete_teacher(school_id: str, teacher_id: str) -> None:
    client = get_client()
    res = await client.table("teachers").select("user_id").eq("school_id", school_id).eq("id", teacher_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
    user_id = res.data[0]["user_id"]
    await client.table("teachers").delete().eq("id", teacher_id).execute()
    if user_id:
        await client.table("users").delete().eq("id", user_id).execute()

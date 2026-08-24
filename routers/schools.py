"""School discovery + registration routes."""
import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from database import get_client
from schemas.school import (
    AdmissionLookupIn,
    AdmissionLookupResult,
    School,
    SchoolBrandOut,
    SchoolProfileOut,
    SchoolProfileUpdateIn,
    SchoolRegisterIn,
    SchoolRegisterOut,
    SchoolSearchIn,
    SchoolSearchResult,
    SchoolStatsOut,
    TrialRegisterIn,
    TrialRegisterOut,
    TrialStatusOut,
    VerifyCodeIn,
)
from services.otp_service import clear, is_verified
from services.school_logo_service import resolve_school_logo, save_school_logo_bytes
from services.school_service import register_school
from services.trial_service import (
    check_and_expire_trials,
    convert_trial_to_permanent,
    get_trial_status,
    register_trial_school,
    stop_trial_and_delete,
)
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/schools", tags=["schools"])
logger = logging.getLogger("eduspace.schools")

_SCHOOL_COLUMNS = "id,school_name,institution_code,logo_url,is_active"
_SEARCH_COLUMNS = (
    "id,school_name,institution_code,logo_url,is_active,city,state,address,phone"
)
_PROFILE_COLUMNS = (
    "id,school_name,institution_code,logo_url,address,city,state,pincode,"
    "email,phone,board,established_date,school_type,level_of_education,total_students,total_teachers,"
    "principal_name,website,gst_number,subscription_plan,admin_email,admin_mobile"
)
_PROFILE_COLUMNS_FALLBACK = (
    "id,school_name,institution_code,logo_url,address,city,state,pincode,"
    "email,phone,board,school_type,level_of_education,total_students,total_teachers,"
    "principal_name,website,gst_number,subscription_plan"
)
_DEFAULT_LOGO_COLOR = "#2563EB"
_EMAIL_OTP_PURPOSE = "school_profile_email"


async def _fetch_school_profile_row(school_id: str) -> dict:
    """Load school profile, tolerating missing optional columns until migrations apply."""
    client = get_client()
    res = (
        await client.table("schools")
        .select(_PROFILE_COLUMNS_FALLBACK)
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    row = dict(res.data[0])
    for col in ("established_date", "admin_email", "admin_mobile"):
        try:
            extra = (
                await client.table("schools")
                .select(col)
                .eq("id", school_id)
                .limit(1)
                .execute()
            )
            if extra.data:
                row[col] = extra.data[0].get(col)
        except Exception:
            logger.warning("%s not available yet for school %s", col, school_id)
    return row


def _to_school(row: dict) -> School:
    """Map a stored schools row to the frontend School shape."""
    name = row.get("school_name") or row.get("name") or ""
    short_name = name.split()[0][:20] if name else ""
    return School(
        id=row["id"],
        name=name,
        short_name=short_name,
        logo_color=row.get("logo_color") or _DEFAULT_LOGO_COLOR,
        institution_code=row.get("institution_code") or "",
    )


def _to_search_result(row: dict) -> SchoolSearchResult:
    base = _to_school(row)
    return SchoolSearchResult(
        **base.model_dump(),
        city=row.get("city"),
        address=row.get("address"),
        state=row.get("state"),
        phone=row.get("phone"),
    )


def _resolve_admin_display_name(row: dict, admin_user: Optional[dict] = None) -> Optional[str]:
    """Person name for Administration → Admin (never the school name)."""
    school = (row.get("school_name") or "").strip().lower()

    def usable(raw: Optional[str]) -> Optional[str]:
        name = (raw or "").strip()
        if not name:
            return None
        if school and name.lower() == school:
            return None
        return name

    admin = admin_user or {}
    # Registration stores administrator full name on schools.principal_name.
    for candidate in (admin.get("full_name"), row.get("principal_name")):
        name = usable(candidate)
        if name:
            return name
    return None


def _to_profile(row: dict, admin_user: Optional[dict] = None) -> SchoolProfileOut:
    established = row.get("established_date")
    if established is not None:
        established = str(established)[:10]
    admin = admin_user or {}
    # Prefer school-stored admin contact (no separate ADM login). Fall back to legacy user row.
    admin_email = row.get("admin_email") or admin.get("email")
    admin_mobile = row.get("admin_mobile") or admin.get("mobile")
    return SchoolProfileOut(
        id=row.get("id"),
        school_name=row.get("school_name") or "",
        institution_code=row.get("institution_code") or "",
        logo_url=row.get("logo_url"),
        address=row.get("address"),
        city=row.get("city"),
        state=row.get("state"),
        pincode=row.get("pincode"),
        school_email=row.get("email"),
        school_phone=row.get("phone"),
        education_board=row.get("board"),
        established_date=established,
        school_type=row.get("school_type"),
        level_of_education=row.get("level_of_education"),
        total_students=row.get("total_students"),
        total_teachers=row.get("total_teachers"),
        principal_name=row.get("principal_name"),
        admin_name=_resolve_admin_display_name(row, admin_user),
        website=row.get("website"),
        gst_number=row.get("gst_number"),
        subscription_plan=row.get("subscription_plan"),
        admin_email=admin_email,
        admin_mobile=admin_mobile,
    )


async def _fetch_school_admin_user(school_id: str) -> Optional[dict]:
    """Canonical School Management (SCH) account for admin name/contact."""
    client = get_client()
    sch = (
        await client.table("users")
        .select("id,email,full_name,mobile,role,user_code")
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .like("user_code", "SCH%")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if sch.data:
        return sch.data[0]
    fallback = (
        await client.table("users")
        .select("id,email,full_name,mobile,role,user_code")
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return fallback.data[0] if fallback.data else None


def _digits_only(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def _phone_matches(school_phone: Optional[str], contact: str) -> bool:
    contact_digits = _digits_only(contact)
    if not contact_digits:
        return False
    raw = (school_phone or "").strip()
    if not raw:
        return False
    for part in re.split(r"[,;\n]+", raw):
        part_digits = _digits_only(part)
        if not part_digits:
            continue
        if contact_digits == part_digits or contact_digits in part_digits or part_digits in contact_digits:
            return True
    return contact_digits in _digits_only(raw)


def _name_matches(value: Optional[str], query: str) -> bool:
    q = query.strip().lower()
    if not q:
        return True
    if not value:
        return False
    return q in value.strip().lower()


def _mobile_matches(stored: Optional[str], contact: str) -> bool:
    contact_digits = _digits_only(contact)
    if not contact_digits:
        return False
    stored_digits = _digits_only(stored or "")
    if not stored_digits:
        return False
    if contact_digits == stored_digits:
        return True
    tail = 10
    if len(contact_digits) >= tail and len(stored_digits) >= tail:
        return contact_digits[-tail:] == stored_digits[-tail:]
    return contact_digits in stored_digits or stored_digits in contact_digits


def _admission_candidates(admission_no: str) -> list[str]:
    ident = admission_no.strip()
    if not ident:
        return []
    candidates = [ident]
    if ident.isdigit():
        n = int(ident)
        candidates.extend([str(n), f"{n:04d}", f"{n:05d}"])
    else:
        candidates.append(ident.upper())
    return list(dict.fromkeys(candidates))


def _filter_by_location(
    rows: list[dict],
    name: str,
    city: str,
    state: str,
) -> list[SchoolSearchResult]:
    name_q = name.strip().lower()
    city_q = city.strip().lower()
    state_q = state.strip().lower()
    results: list[SchoolSearchResult] = []
    for row in rows:
        school_name = (row.get("school_name") or "").lower()
        if name_q and name_q not in school_name:
            continue
        if city_q and city_q not in (row.get("city") or "").lower():
            continue
        if state_q and state_q not in (row.get("state") or "").lower():
            continue
        results.append(_to_search_result(row))
    return results


async def _school_ids_by_admission(admission_no: str) -> set[str]:
    client = get_client()
    school_ids: set[str] = set()
    for candidate in _admission_candidates(admission_no):
        res = (
            await client.table("users")
            .select("school_id")
            .eq("role", "student")
            .eq("admission_no", candidate)
            .eq("is_active", True)
            .execute()
        )
        for row in res.data or []:
            sid = row.get("school_id")
            if sid:
                school_ids.add(sid)
    return school_ids


async def _search_by_admission_and_contact(
    rows: list[dict],
    admission_no: str,
    contact: str,
) -> list[SchoolSearchResult]:
    admission_ids = await _school_ids_by_admission(admission_no)
    if not admission_ids:
        return []
    results: list[SchoolSearchResult] = []
    for row in rows:
        if row.get("id") not in admission_ids:
            continue
        if not _phone_matches(row.get("phone"), contact):
            continue
        results.append(_to_search_result(row))
    return results


async def _load_active_schools() -> list[dict]:
    client = get_client()
    res = (
        await client.table("schools")
        .select(_SEARCH_COLUMNS)
        .eq("is_active", True)
        .order("school_name")
        .limit(500)
        .execute()
    )
    return res.data or []


async def search_schools(body: SchoolSearchIn) -> list[SchoolSearchResult]:
    """Step 1: school name + city + state. Step 2: admission number + contact."""
    name = (body.school_name or "").strip()
    city = (body.city or "").strip()
    state = (body.state or "").strip()
    admission_no = (body.admission_no or "").strip()
    contact = (body.contact or "").strip()

    rows = await _load_active_schools()

    has_location = bool(name and city and state)
    has_student_lookup = bool(admission_no and contact)

    if has_location:
        location_results = _filter_by_location(rows, name, city, state)
        if location_results:
            return location_results

    if has_student_lookup:
        return await _search_by_admission_and_contact(rows, admission_no, contact)

    return []


async def _resolve_school_id_by_code(institution_code: str) -> str:
    client = get_client()
    code = institution_code.strip().upper()
    res = (
        await client.table("schools")
        .select("id")
        .eq("institution_code", code)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid institution code")
    return res.data[0]["id"]


async def lookup_student_admission(body: AdmissionLookupIn) -> List[AdmissionLookupResult]:
    """Find a student's admission number within a school."""
    name_q = (body.student_name or "").strip()
    father_q = (body.father_name or "").strip()
    mother_q = (body.mother_name or "").strip()
    contact_q = (body.contact or "").strip()

    if not any([name_q, father_q, mother_q, contact_q]):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Enter at least one of student name, father name, mother name, or contact number.",
        )

    school_id = await _resolve_school_id_by_code(body.institution_code)
    client = get_client()
    students_res = (
        await client.table("students")
        .select("user_id,father_name,mother_name,guardian_mobile,alternate_mobile,admission_no")
        .eq("school_id", school_id)
        .limit(1000)
        .execute()
    )
    profiles = students_res.data or []
    if not profiles:
        return []

    user_ids = [p["user_id"] for p in profiles if p.get("user_id")]
    users_res = (
        await client.table("users")
        .select("id,full_name,mobile,admission_no,is_active")
        .in_("id", user_ids)
        .eq("is_active", True)
        .execute()
    )
    users_map = {u["id"]: u for u in (users_res.data or [])}

    results: list[AdmissionLookupResult] = []
    for profile in profiles:
        user = users_map.get(profile.get("user_id"))
        if not user:
            continue

        full_name = user.get("full_name") or ""
        father_name = profile.get("father_name")
        mother_name = profile.get("mother_name")
        guardian_mobile = profile.get("guardian_mobile")
        alternate_mobile = profile.get("alternate_mobile")
        user_mobile = user.get("mobile")

        if not _name_matches(full_name, name_q):
            continue
        if not _name_matches(father_name, father_q):
            continue
        if not _name_matches(mother_name, mother_q):
            continue
        if contact_q and not any(
            _mobile_matches(v, contact_q) for v in (guardian_mobile, alternate_mobile, user_mobile)
        ):
            continue

        admission_no = (user.get("admission_no") or profile.get("admission_no") or "").strip()
        if not admission_no:
            continue

        results.append(
            AdmissionLookupResult(
                full_name=full_name,
                father_name=father_name,
                mother_name=mother_name,
                admission_no=admission_no,
            )
        )

    results.sort(key=lambda r: r.full_name.lower())
    return results[:25]


@router.get("/brand", response_model=SchoolBrandOut)
async def get_my_school_brand(user: dict = Depends(current_user)) -> SchoolBrandOut:
    """School name/logo/contact for ID cards and headers — any school member can read."""
    school_id = user.get("school_id")
    if not school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    client = get_client()
    res = (
        await client.table("schools")
        .select("school_name,app_display_name,logo_url,use_school_logo,email,phone,address,city")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    row = res.data[0]
    return SchoolBrandOut(
        school_name=(row.get("school_name") or "").strip(),
        app_display_name=row.get("app_display_name"),
        logo_url=row.get("logo_url"),
        use_school_logo=bool(row.get("use_school_logo", False)),
        school_email=row.get("email"),
        school_phone=row.get("phone"),
        address=row.get("address"),
        city=row.get("city"),
    )


@router.get("/me", response_model=SchoolProfileOut)
async def get_my_school_profile(
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> SchoolProfileOut:
    school_id = user.get("school_id")
    if not school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    row = await _fetch_school_profile_row(school_id)
    admin_user = await _fetch_school_admin_user(school_id)
    return _to_profile(row, admin_user or user)


@router.get("/{school_id}/logo/{filename}")
async def get_school_logo(school_id: str, filename: str):
    path, content_type = resolve_school_logo(school_id, filename)
    return FileResponse(path, media_type=content_type)


@router.post("/me/logo")
async def upload_my_school_logo(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> dict:
    """Upload or replace the current school's logo."""
    school_id = user.get("school_id")
    if not school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")

    content = await file.read()
    logo_url = save_school_logo_bytes(
        school_id,
        content,
        filename=file.filename,
        content_type=file.content_type,
    )

    client = get_client()
    updated = (
        await client.table("schools")
        .update({"logo_url": logo_url})
        .eq("id", school_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save school logo")
    return {"logo_url": logo_url}


@router.put("/me", response_model=SchoolProfileOut)
async def update_my_school_profile(
    body: SchoolProfileUpdateIn,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> SchoolProfileOut:
    school_id = user.get("school_id")
    if not school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")

    client = get_client()
    current = await _fetch_school_profile_row(school_id)

    updates: dict = {}
    if body.app_display_name is not None:
        name = body.app_display_name.strip()
        if len(name) < 2:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "App name must be at least 2 characters")
        updates["app_display_name"] = name or None
    if body.use_school_logo is not None:
        if body.use_school_logo and not current.get("logo_url"):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Upload your school logo in School Profile first, then try again.",
            )
        updates["use_school_logo"] = body.use_school_logo
    if body.education_board is not None:
        updates["board"] = body.education_board.strip() or None
    if body.established_date is not None:
        value = body.established_date.strip()
        updates["established_date"] = value or None
    if body.school_phone is not None:
        updates["phone"] = body.school_phone.strip() or None
    if body.address is not None:
        updates["address"] = body.address.strip() or None
    if body.city is not None:
        updates["city"] = body.city.strip() or None
    if body.state is not None:
        updates["state"] = body.state.strip() or None
    if body.website is not None:
        updates["website"] = body.website.strip() or None

    current_email = (current.get("email") or "").strip().lower()
    next_email = (str(body.school_email).strip().lower() if body.school_email is not None else current_email)

    if body.school_email is not None and next_email != current_email:
        if not current_email:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Current school email is missing. Contact support before changing email.",
            )
        if not is_verified(current_email, purpose=_EMAIL_OTP_PURPOSE):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Verify your current school email with OTP before changing it.",
            )
        if not is_verified(next_email, purpose=_EMAIL_OTP_PURPOSE):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Verify the new school email with OTP before saving.",
            )
        taken = (
            await client.table("users")
            .select("id")
            .eq("email", next_email)
            .limit(1)
            .execute()
        )
        if taken.data:
            raise HTTPException(status.HTTP_409_CONFLICT, "New school email is already registered")
        school_email_taken = (
            await client.table("schools")
            .select("id")
            .eq("email", next_email)
            .neq("id", school_id)
            .limit(1)
            .execute()
        )
        if school_email_taken.data:
            raise HTTPException(status.HTTP_409_CONFLICT, "New school email is already registered")
        updates["email"] = next_email

    if not updates:
        admin_user = await _fetch_school_admin_user(school_id)
        return _to_profile(current, admin_user or user)

    try:
        updated = (
            await client.table("schools")
            .update(updates)
            .eq("id", school_id)
            .execute()
        )
    except Exception:
        if "established_date" in updates:
            updates.pop("established_date", None)
            if not updates:
                admin_user = await _fetch_school_admin_user(school_id)
                return _to_profile(current, admin_user or user)
            updated = (
                await client.table("schools")
                .update(updates)
                .eq("id", school_id)
                .execute()
            )
        else:
            raise
    if not updated.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update school profile")

    if "email" in updates and current_email:
        await (
            client.table("users")
            .update({"email": next_email})
            .eq("school_id", school_id)
            .eq("email", current_email)
            .execute()
        )
        clear(current_email, purpose=_EMAIL_OTP_PURPOSE)
        clear(next_email, purpose=_EMAIL_OTP_PURPOSE)

    admin_user = await _fetch_school_admin_user(school_id)
    return _to_profile(updated.data[0], admin_user or user)


@router.get("", response_model=List[School])
async def list_schools() -> List[School]:
    client = get_client()
    res = (
        await client.table("schools")
        .select(_SCHOOL_COLUMNS)
        .eq("is_active", True)
        .order("school_name")
        .limit(200)
        .execute()
    )
    return [_to_school(row) for row in (res.data or [])]


# Staff roles counted in the "staff" bucket for developer stats.
_STAFF_STAT_ROLES = {
    "receptionist", "accountant", "librarian", "transport_manager",
    "hostel_warden", "hostel_manager", "school_doctor",
    "principal", "vice_principal",
}


@router.get("/all-stats", response_model=List[SchoolStatsOut])
async def all_school_stats(
    user: dict = Depends(require_roles("developer")),
) -> List[SchoolStatsOut]:
    """Developer-only: list every school with student/teacher/staff counts."""
    client = get_client()
    schools_res = (
        await client.table("schools")
        .select("id,school_name,institution_code,is_active,is_trial,city,state,subscription_plan")
        .order("school_name")
        .limit(1000)
        .execute()
    )
    schools = schools_res.data or []
    if not schools:
        return []

    school_ids = [s["id"] for s in schools]

    # Count users per school grouped by role bucket.
    users_res = (
        await client.table("users")
        .select("school_id,role,is_active")
        .in_("school_id", school_ids)
        .execute()
    )
    counts: dict[str, dict[str, int]] = {}
    for row in users_res.data or []:
        sid = row.get("school_id")
        if not sid:
            continue
        if sid not in counts:
            counts[sid] = {"student": 0, "teacher": 0, "staff": 0}
        role = row.get("role") or ""
        if not row.get("is_active", True):
            continue
        if role == "student":
            counts[sid]["student"] += 1
        elif role == "teacher":
            counts[sid]["teacher"] += 1
        elif role in _STAFF_STAT_ROLES or role == "school_admin":
            counts[sid]["staff"] += 1

    results: list[SchoolStatsOut] = []
    for s in schools:
        sid = s["id"]
        c = counts.get(sid, {"student": 0, "teacher": 0, "staff": 0})
        results.append(SchoolStatsOut(
            id=sid,
            school_name=s.get("school_name") or "",
            institution_code=s.get("institution_code") or "",
            is_active=s.get("is_active", True),
            is_trial=s.get("is_trial", False),
            city=s.get("city"),
            state=s.get("state"),
            student_count=c["student"],
            teacher_count=c["teacher"],
            staff_count=c["staff"],
            subscription_plan=s.get("subscription_plan"),
        ))
    return results


@router.get("/payment-overview")
async def payment_overview(
    user: dict = Depends(require_roles("developer")),
) -> dict:
    """Developer-only: payment/subscription overview across all schools."""
    client = get_client()
    schools_res = (
        await client.table("schools")
        .select("id,school_name,institution_code,is_active,is_trial,subscription_plan,city,state")
        .order("school_name")
        .limit(1000)
        .execute()
    )
    schools = schools_res.data or []
    if not schools:
        return {"schools": [], "total_revenue": 0, "total_paid": 0, "total_pending": 0}

    school_ids = [s["id"] for s in schools]

    # Fee payment totals per school
    payments_res = (
        await client.table("fee_payments")
        .select("school_id,payment_status,total")
        .in_("school_id", school_ids)
        .execute()
    )
    pay_stats: dict[str, dict] = {}
    for row in payments_res.data or []:
        sid = row.get("school_id")
        if not sid:
            continue
        if sid not in pay_stats:
            pay_stats[sid] = {"revenue": 0, "paid_count": 0, "pending_count": 0}
        ps = (row.get("payment_status") or "").lower()
        total = float(row.get("total") or 0)
        if ps == "paid":
            pay_stats[sid]["revenue"] += total
            pay_stats[sid]["paid_count"] += 1
        elif ps in ("created", "pending"):
            pay_stats[sid]["pending_count"] += 1

    schools_out = []
    total_revenue = 0.0
    total_paid = 0
    total_pending = 0
    for s in schools:
        sid = s["id"]
        ps = pay_stats.get(sid, {"revenue": 0, "paid_count": 0, "pending_count": 0})
        revenue = round(ps["revenue"], 2)
        total_revenue += revenue
        total_paid += ps["paid_count"]
        total_pending += ps["pending_count"]
        schools_out.append({
            "id": sid,
            "school_name": s.get("school_name") or "",
            "institution_code": s.get("institution_code") or "",
            "is_active": s.get("is_active", True),
            "is_trial": s.get("is_trial", False),
            "subscription_plan": s.get("subscription_plan") or "free",
            "city": s.get("city"),
            "state": s.get("state"),
            "revenue": revenue,
            "paid_count": ps["paid_count"],
            "pending_count": ps["pending_count"],
        })

    return {
        "schools": schools_out,
        "total_revenue": round(total_revenue, 2),
        "total_paid": total_paid,
        "total_pending": total_pending,
    }


@router.post("/search", response_model=List[SchoolSearchResult])
async def search_schools_route(body: SchoolSearchIn) -> List[SchoolSearchResult]:
    return await search_schools(body)


@router.post("/lookup-admission", response_model=List[AdmissionLookupResult])
async def lookup_admission_route(body: AdmissionLookupIn) -> List[AdmissionLookupResult]:
    return await lookup_student_admission(body)


@router.post("/verify", response_model=School)
async def verify_institution_code(body: VerifyCodeIn) -> School:
    code = body.code.strip().upper()
    client = get_client()
    res = (
        await client.table("schools")
        .select(_SCHOOL_COLUMNS)
        .eq("institution_code", code)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid institution code")
    return _to_school(res.data[0])


@router.post("/register", response_model=SchoolRegisterOut, status_code=status.HTTP_201_CREATED)
async def register_school_route(body: SchoolRegisterIn) -> SchoolRegisterOut:
    result = await register_school(body)
    return SchoolRegisterOut(
        message="School registered successfully. Login credentials have been sent to the school email.",
        school_id=result.get("school_id"),
        institution_code=result.get("institution_code"),
    )


@router.post("/trial-register", response_model=TrialRegisterOut, status_code=status.HTTP_201_CREATED)
async def trial_register_route(body: TrialRegisterIn) -> TrialRegisterOut:
    result = await register_trial_school(body)
    return TrialRegisterOut(
        message="Free trial activated! Login credentials have been sent to your school email. The trial is valid for 7 days.",
        institution_code=result.get("institution_code"),
    )


@router.get("/trial-status", response_model=TrialStatusOut)
async def trial_status_route(user: dict = Depends(current_user)) -> TrialStatusOut:
    school_id = user.get("school_id")
    if not school_id:
        return TrialStatusOut(is_trial=False)
    status = await get_trial_status(school_id)
    return TrialStatusOut(**status)


@router.post("/trial-convert")
async def trial_convert_route(user: dict = Depends(require_roles("school_admin"))) -> dict:
    school_id = user.get("school_id")
    if not school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    result = await convert_trial_to_permanent(school_id)
    return result


@router.post("/trial-stop")
async def trial_stop_route(user: dict = Depends(require_roles("school_admin"))) -> dict:
    school_id = user.get("school_id")
    if not school_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    result = await stop_trial_and_delete(school_id)
    return result


@router.post("/trial-check-expired")
async def trial_check_expired_route() -> dict:
    count = await check_and_expire_trials()
    return {"expired_count": count}

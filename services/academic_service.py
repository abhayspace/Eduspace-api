"""Academic structure — classes, sections, subjects (scoped per school_id)."""
from typing import List, Optional, Set

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

from database import get_client
from schemas.people import ClassOut, ClassSectionOut, SectionOut, SubjectOut, TeacherBriefOut, TeacherOut, TeacherUpdateIn
from services import teacher_service

DEFAULT_SUBJECTS = [
    "Math", "Science", "Physics", "Chemistry", "Biology",
    "English", "Hindi", "Computer", "History", "Geography",
    "Economics", "Political Science", "Sanskrit", "Art", "Physical Education",
]


def _missing_table_error(exc: APIError) -> bool:
    if getattr(exc, "code", None) == "PGRST205":
        return True
    payload = exc.args[0] if exc.args else {}
    if isinstance(payload, dict):
        return payload.get("code") == "PGRST205"
    return False


def _is_unique_violation(exc: APIError) -> bool:
    if getattr(exc, "code", None) == "23505":
        return True
    return "duplicate key" in str(exc).lower() or "unique constraint" in str(exc).lower()


def _raise_if_missing_table(exc: APIError, table: str) -> None:
    if _missing_table_error(exc):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Database table '{table}' is missing. "
                "Run backend/migrations/004_academic_tables.sql in Supabase SQL Editor, "
                "or set DATABASE_URL in backend/.env and run: python migrate.py"
            ),
        ) from exc
    raise exc


def _normalize_class_name(name: str) -> str:
    return (name or "").strip()


def _class_name_key(name: str) -> str:
    return _normalize_class_name(name).lower()


def _parse_grade_level(name: str) -> Optional[str]:
    cleaned = _normalize_class_name(name)
    if cleaned.lower().startswith("class "):
        suffix = cleaned[6:].strip()
        if suffix.isdigit():
            return suffix
    return None


_CLASS_SEQUENCE = (
    "nursery",
    "lower kindergarten",
    "upper kindergarten",
)


def _class_sort_key(name: str, grade_level: Optional[str] = None) -> tuple:
    normalized = _class_name_key(name)
    if normalized in _CLASS_SEQUENCE:
        return (0, _CLASS_SEQUENCE.index(normalized), "")
    grade = grade_level if grade_level and str(grade_level).isdigit() else _parse_grade_level(name)
    if grade:
        return (1, int(grade), normalized)
    return (2, 0, normalized)


def _normalize_sections(sections: List[str]) -> List[str]:
    normalized: List[str] = []
    seen: Set[str] = set()
    for s in sections or []:
        label = (s or "").strip().upper()
        if not label or label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    return normalized


def _map_sections(section_rows: List[dict]) -> List[ClassSectionOut]:
    items = [
        ClassSectionOut(id=row["id"], name=(row.get("name") or "").strip().upper())
        for row in section_rows
        if row.get("id") and row.get("name")
    ]
    return sorted(items, key=lambda s: (len(s.name), s.name))


async def _find_class_by_name(school_id: str, name: str) -> Optional[dict]:
    """Find a class for this school only (case-insensitive name match)."""
    client = get_client()
    try:
        res = await (
            client.table("classes")
            .select("id,name,grade_level")
            .eq("school_id", school_id)
            .execute()
        )
    except APIError as exc:
        _raise_if_missing_table(exc, "classes")
        return None

    needle = _class_name_key(name)
    for row in res.data or []:
        if _class_name_key(row.get("name") or "") == needle:
            return row
    return None


async def _existing_section_names(school_id: str, class_id: str) -> Set[str]:
    client = get_client()
    res = await (
        client.table("sections")
        .select("name")
        .eq("school_id", school_id)
        .eq("class_id", class_id)
        .execute()
    )
    return {(row.get("name") or "").strip().upper() for row in (res.data or []) if row.get("name")}


async def _class_out_for_id(school_id: str, class_id: str) -> ClassOut:
    client = get_client()
    res = await (
        client.table("classes")
        .select("id,name,grade_level,sections(id,name)")
        .eq("school_id", school_id)
        .eq("id", class_id)
        .limit(1)
        .execute()
    )
    row = (res.data or [None])[0]
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found.")
    section_rows = row.pop("sections", None) or []
    return ClassOut(
        id=row["id"],
        name=row["name"],
        grade_level=row.get("grade_level"),
        sections=_map_sections(section_rows),
    )


async def ensure_defaults(school_id: str) -> None:
    """Seed default subjects for this school if none exist."""
    client = get_client()
    try:
        subj = await client.table("subjects").select("id").eq("school_id", school_id).limit(1).execute()
        if not subj.data:
            rows = [{"school_id": school_id, "name": n, "code": n[:3].upper()} for n in DEFAULT_SUBJECTS]
            await client.table("subjects").insert(rows).execute()
    except APIError as exc:
        table = "subjects"
        if "classes" in str(exc):
            table = "classes"
        elif "sections" in str(exc):
            table = "sections"
        _raise_if_missing_table(exc, table)


async def list_classes(school_id: str) -> List[ClassOut]:
    await ensure_defaults(school_id)
    client = get_client()
    try:
        res = await (
            client.table("classes")
            .select("id,name,grade_level,sections(id,name)")
            .eq("school_id", school_id)
            .order("name")
            .execute()
        )
    except APIError as exc:
        _raise_if_missing_table(exc, "classes")

    items: List[ClassOut] = []
    for row in res.data or []:
        section_rows = row.pop("sections", None) or []
        items.append(
            ClassOut(
                id=row["id"],
                name=row["name"],
                grade_level=row.get("grade_level"),
                sections=_map_sections(section_rows),
            )
        )
    items.sort(key=lambda item: _class_sort_key(item.name, item.grade_level))
    return items


async def _add_sections(school_id: str, class_id: str, sections: List[str]) -> None:
    if not sections:
        return
    client = get_client()
    existing_names = await _existing_section_names(school_id, class_id)
    to_insert = [sec for sec in sections if sec not in existing_names]
    if not to_insert:
        return
    try:
        await client.table("sections").insert(
            [{"school_id": school_id, "class_id": class_id, "name": sec} for sec in to_insert]
        ).execute()
    except APIError as exc:
        if _is_unique_violation(exc):
            return
        _raise_if_missing_table(exc, "sections")


async def create_class(school_id: str, name: str, sections: List[str]) -> ClassOut:
    """Create a class for one school, or add sections to an existing class name."""
    await ensure_defaults(school_id)
    client = get_client()

    cleaned_name = _normalize_class_name(name)
    if not cleaned_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Class name is required.")

    normalized_sections = _normalize_sections(sections)
    if not normalized_sections:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Select at least one section.")

    existing = await _find_class_by_name(school_id, cleaned_name)
    if existing:
        class_id = existing["id"]
        existing_names = await _existing_section_names(school_id, class_id)
        duplicates = [s for s in normalized_sections if s in existing_names]
        new_sections = [s for s in normalized_sections if s not in existing_names]
        if not new_sections:
            joined = ", ".join(duplicates)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"{cleaned_name} section(s) {joined} already exist for your school.",
            )
        await _add_sections(school_id, class_id, new_sections)
        return await _class_out_for_id(school_id, class_id)

    grade_level = _parse_grade_level(cleaned_name)
    try:
        created = await (
            client.table("classes")
            .insert({"school_id": school_id, "name": cleaned_name, "grade_level": grade_level})
            .execute()
        )
    except APIError as exc:
        if _is_unique_violation(exc):
            existing = await _find_class_by_name(school_id, cleaned_name)
            if not existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Class already exists for your school. Refresh and try adding sections.",
                ) from exc
            await _add_sections(school_id, existing["id"], normalized_sections)
            return await _class_out_for_id(school_id, existing["id"])
        _raise_if_missing_table(exc, "classes")

    row = (created.data or [None])[0]
    if not row:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create class.")

    await _add_sections(school_id, row["id"], normalized_sections)
    return await _class_out_for_id(school_id, row["id"])


async def list_sections(school_id: str, class_id: Optional[str] = None) -> List[SectionOut]:
    await ensure_defaults(school_id)
    client = get_client()
    query = client.table("sections").select("id,class_id,name").eq("school_id", school_id)
    if class_id:
        query = query.eq("class_id", class_id)
    try:
        res = await query.order("name").execute()
    except APIError as exc:
        _raise_if_missing_table(exc, "sections")
    return [SectionOut(**row) for row in (res.data or [])]


async def list_subjects(school_id: str) -> List[SubjectOut]:
    await ensure_defaults(school_id)
    client = get_client()
    try:
        res = await client.table("subjects").select("id,name,code").eq("school_id", school_id).order("name").execute()
    except APIError as exc:
        _raise_if_missing_table(exc, "subjects")
    return [SubjectOut(**row) for row in (res.data or [])]


async def delete_class(school_id: str, class_id: str) -> None:
    client = get_client()
    try:
        existing = await (
            client.table("classes")
            .select("id")
            .eq("school_id", school_id)
            .eq("id", class_id)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        _raise_if_missing_table(exc, "classes")

    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class not found.")

    await client.table("classes").delete().eq("school_id", school_id).eq("id", class_id).execute()


async def delete_section(school_id: str, section_id: str) -> None:
    client = get_client()
    try:
        section = await (
            client.table("sections")
            .select("id,class_id")
            .eq("school_id", school_id)
            .eq("id", section_id)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        _raise_if_missing_table(exc, "sections")

    if not section.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found.")

    class_id = section.data[0]["class_id"]
    await client.table("sections").delete().eq("school_id", school_id).eq("id", section_id).execute()

    remaining = await (
        client.table("sections")
        .select("id")
        .eq("school_id", school_id)
        .eq("class_id", class_id)
        .limit(1)
        .execute()
    )
    if not remaining.data:
        await client.table("classes").delete().eq("school_id", school_id).eq("id", class_id).execute()


async def update_section(school_id: str, section_id: str, name: str) -> SectionOut:
    """Rename a section within its class (A–Z). Rejects duplicates in the same class."""
    normalized = _normalize_sections([name])
    if not normalized:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Section name is required.")
    new_name = normalized[0]

    client = get_client()
    try:
        existing = await (
            client.table("sections")
            .select("id,class_id,name")
            .eq("school_id", school_id)
            .eq("id", section_id)
            .limit(1)
            .execute()
        )
    except APIError as exc:
        _raise_if_missing_table(exc, "sections")

    if not existing.data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Section not found.")

    row = existing.data[0]
    class_id = row["class_id"]
    current = (row.get("name") or "").strip().upper()
    if new_name == current:
        return SectionOut(id=row["id"], class_id=class_id, name=current)

    taken = await _existing_section_names(school_id, class_id)
    if new_name in taken:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Section {new_name} already exists for this class.",
        )

    try:
        updated = await (
            client.table("sections")
            .update({"name": new_name})
            .eq("school_id", school_id)
            .eq("id", section_id)
            .execute()
        )
    except APIError as exc:
        _raise_if_missing_table(exc, "sections")

    out = (updated.data or [{}])[0]
    return SectionOut(
        id=out.get("id") or section_id,
        class_id=out.get("class_id") or class_id,
        name=(out.get("name") or new_name).strip().upper(),
    )


async def list_teachers_brief(school_id: str) -> List[TeacherBriefOut]:
    client = get_client()
    try:
        res = await (
            client.table("teachers")
            .select(
                "id,user_id,is_class_teacher,class_teacher_class_id,class_teacher_section_id"
            )
            .eq("school_id", school_id)
            .execute()
        )
    except APIError as exc:
        # Older DBs may lack class-teacher columns — fall back to id/user_id only.
        try:
            res = await client.table("teachers").select("id,user_id").eq("school_id", school_id).execute()
        except APIError as inner:
            _raise_if_missing_table(inner, "teachers")
            raise exc from inner

    rows = res.data or []
    if not rows:
        return []

    user_ids = [row["user_id"] for row in rows if row.get("user_id")]
    users_res = await client.table("users").select("id,full_name").in_("id", user_ids).execute()
    names = {row["id"]: row.get("full_name") or "Teacher" for row in (users_res.data or [])}
    return [
        TeacherBriefOut(
            id=row["id"],
            full_name=names.get(row.get("user_id"), "Teacher"),
            is_class_teacher=bool(row.get("is_class_teacher")),
            class_teacher_class_id=row.get("class_teacher_class_id"),
            class_teacher_section_id=row.get("class_teacher_section_id"),
        )
        for row in rows
    ]


async def assign_class_teacher(
    school_id: str,
    teacher_id: str,
    class_id: str,
    section_id: str,
) -> TeacherOut:
    return await teacher_service.update_teacher(
        school_id,
        teacher_id,
        TeacherUpdateIn(
            is_class_teacher=True,
            class_teacher_class_id=class_id,
            class_teacher_section_id=section_id,
        ),
    )

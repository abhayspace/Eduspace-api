"""Class syllabus: syllabus per class-section, terms inside it, chapters inside terms."""
from datetime import datetime, timezone
from typing import List

from fastapi import HTTPException, status

from database import get_client
from schemas.syllabus import (
    SyllabusChapterIn,
    SyllabusChapterOut,
    SyllabusChapterStatusIn,
    SyllabusCreateIn,
    SyllabusOut,
    SyllabusTermIn,
    SyllabusTermOut,
)

SYLLABI = "syllabi"
TERMS = "syllabus_terms"
CHAPTERS = "syllabus_chapters"


def _chapter_out(row: dict) -> SyllabusChapterOut:
    return SyllabusChapterOut(
        id=row["id"],
        term_id=row["term_id"],
        title=row.get("title") or "",
        description=row.get("description") or "",
        sort_order=row.get("sort_order") or 0,
        completed=bool(row.get("completed")),
        completed_at=row.get("completed_at"),
        created_at=row.get("created_at"),
    )


async def _next_sort_order(table: str, field: str, value: str) -> int:
    client = get_client()
    res = (
        await client.table(table)
        .select("sort_order")
        .eq(field, value)
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        return 0
    return (res.data[0].get("sort_order") or 0) + 1


async def _resolve_class_section(school_id: str, class_id: str, section_id: str) -> tuple[str, str]:
    client = get_client()
    cls = (
        await client.table("classes")
        .select("name")
        .eq("school_id", school_id)
        .eq("id", class_id)
        .limit(1)
        .execute()
    )
    if not cls.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    sec = (
        await client.table("sections")
        .select("name,class_id")
        .eq("school_id", school_id)
        .eq("id", section_id)
        .limit(1)
        .execute()
    )
    if not sec.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    if sec.data[0].get("class_id") != class_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Section does not belong to this class")
    return cls.data[0]["name"], sec.data[0]["name"]


async def _terms_for(school_id: str, syllabus_ids: List[str]) -> dict[str, List[SyllabusTermOut]]:
    if not syllabus_ids:
        return {}
    client = get_client()
    term_res = (
        await client.table(TERMS)
        .select("*")
        .eq("school_id", school_id)
        .in_("syllabus_id", syllabus_ids)
        .order("sort_order")
        .execute()
    )
    terms = term_res.data or []
    chapters_by_term: dict[str, List[SyllabusChapterOut]] = {}
    if terms:
        chapter_res = (
            await client.table(CHAPTERS)
            .select("*")
            .eq("school_id", school_id)
            .in_("term_id", [t["id"] for t in terms])
            .order("sort_order")
            .execute()
        )
        for row in chapter_res.data or []:
            chapters_by_term.setdefault(row["term_id"], []).append(_chapter_out(row))

    grouped: dict[str, List[SyllabusTermOut]] = {}
    for term in terms:
        grouped.setdefault(term["syllabus_id"], []).append(
            SyllabusTermOut(
                id=term["id"],
                syllabus_id=term["syllabus_id"],
                name=term.get("name") or "",
                sort_order=term.get("sort_order") or 0,
                chapters=chapters_by_term.get(term["id"], []),
            )
        )
    return grouped


def _syllabus_out(row: dict, terms: List[SyllabusTermOut]) -> SyllabusOut:
    return SyllabusOut(
        id=row["id"],
        class_id=row["class_id"],
        section_id=row["section_id"],
        class_name=row.get("class_name") or "",
        section_name=row.get("section_name") or "",
        terms=terms,
        created_at=row.get("created_at"),
    )


async def list_syllabi(school_id: str) -> List[SyllabusOut]:
    client = get_client()
    res = (
        await client.table(SYLLABI)
        .select("*")
        .eq("school_id", school_id)
        .order("class_name")
        .limit(500)
        .execute()
    )
    rows = res.data or []
    grouped = await _terms_for(school_id, [row["id"] for row in rows])
    return [_syllabus_out(row, grouped.get(row["id"], [])) for row in rows]


async def get_syllabus(school_id: str, syllabus_id: str) -> SyllabusOut:
    client = get_client()
    res = (
        await client.table(SYLLABI)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", syllabus_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Syllabus not found")
    grouped = await _terms_for(school_id, [syllabus_id])
    return _syllabus_out(res.data[0], grouped.get(syllabus_id, []))


async def create_syllabus(school_id: str, user_id: str, body: SyllabusCreateIn) -> SyllabusOut:
    class_name, section_name = await _resolve_class_section(
        school_id, body.class_id, body.section_id
    )
    client = get_client()
    existing = (
        await client.table(SYLLABI)
        .select("id")
        .eq("school_id", school_id)
        .eq("class_id", body.class_id)
        .eq("section_id", body.section_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"A syllabus already exists for {class_name} - {section_name}",
        )
    res = (
        await client.table(SYLLABI)
        .insert(
            {
                "school_id": school_id,
                "class_id": body.class_id,
                "section_id": body.section_id,
                "class_name": class_name,
                "section_name": section_name,
                "created_by_user_id": user_id,
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create syllabus")
    return _syllabus_out(res.data[0], [])


async def delete_syllabus(school_id: str, syllabus_id: str) -> None:
    await get_syllabus(school_id, syllabus_id)
    client = get_client()
    await client.table(SYLLABI).delete().eq("id", syllabus_id).execute()


async def _term_row(school_id: str, term_id: str) -> dict:
    client = get_client()
    res = (
        await client.table(TERMS)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", term_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")
    return res.data[0]


async def add_term(school_id: str, syllabus_id: str, body: SyllabusTermIn) -> SyllabusTermOut:
    await get_syllabus(school_id, syllabus_id)
    client = get_client()
    res = (
        await client.table(TERMS)
        .insert(
            {
                "school_id": school_id,
                "syllabus_id": syllabus_id,
                "name": body.name.strip(),
                "sort_order": await _next_sort_order(TERMS, "syllabus_id", syllabus_id),
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create term")
    row = res.data[0]
    return SyllabusTermOut(
        id=row["id"],
        syllabus_id=row["syllabus_id"],
        name=row.get("name") or "",
        sort_order=row.get("sort_order") or 0,
        chapters=[],
    )


async def rename_term(school_id: str, term_id: str, body: SyllabusTermIn) -> SyllabusTermOut:
    row = await _term_row(school_id, term_id)
    client = get_client()
    await client.table(TERMS).update({"name": body.name.strip()}).eq("id", term_id).execute()
    grouped = await _terms_for(school_id, [row["syllabus_id"]])
    for term in grouped.get(row["syllabus_id"], []):
        if term.id == term_id:
            return term
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Term not found")


async def delete_term(school_id: str, term_id: str) -> None:
    await _term_row(school_id, term_id)
    client = get_client()
    await client.table(TERMS).delete().eq("id", term_id).execute()


async def _chapter_row(school_id: str, chapter_id: str) -> dict:
    client = get_client()
    res = (
        await client.table(CHAPTERS)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", chapter_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chapter not found")
    return res.data[0]


async def add_chapter(
    school_id: str,
    term_id: str,
    body: SyllabusChapterIn,
) -> SyllabusChapterOut:
    await _term_row(school_id, term_id)
    client = get_client()
    res = (
        await client.table(CHAPTERS)
        .insert(
            {
                "school_id": school_id,
                "term_id": term_id,
                "title": body.title.strip(),
                "description": body.description.strip(),
                "sort_order": await _next_sort_order(CHAPTERS, "term_id", term_id),
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to add chapter")
    return _chapter_out(res.data[0])


async def update_chapter(
    school_id: str,
    chapter_id: str,
    body: SyllabusChapterIn,
) -> SyllabusChapterOut:
    await _chapter_row(school_id, chapter_id)
    client = get_client()
    updates = {"title": body.title.strip(), "description": body.description.strip()}
    res = await client.table(CHAPTERS).update(updates).eq("id", chapter_id).execute()
    if res.data:
        return _chapter_out(res.data[0])
    return _chapter_out(await _chapter_row(school_id, chapter_id))


async def set_chapter_completed(
    school_id: str,
    chapter_id: str,
    body: SyllabusChapterStatusIn,
) -> SyllabusChapterOut:
    await _chapter_row(school_id, chapter_id)
    client = get_client()
    updates = {
        "completed": body.completed,
        "completed_at": datetime.now(timezone.utc).isoformat() if body.completed else None,
    }
    res = await client.table(CHAPTERS).update(updates).eq("id", chapter_id).execute()
    if res.data:
        return _chapter_out(res.data[0])
    return _chapter_out(await _chapter_row(school_id, chapter_id))


async def delete_chapter(school_id: str, chapter_id: str) -> None:
    await _chapter_row(school_id, chapter_id)
    client = get_client()
    await client.table(CHAPTERS).delete().eq("id", chapter_id).execute()

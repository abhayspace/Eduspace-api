import logging
from typing import Optional
from fastapi import HTTPException, status, UploadFile
from datetime import date
from pathlib import Path
import uuid
import re

from postgrest import APIError

from database import get_client
from schemas.achievements import (
    AchievementCreate,
    AchievementUpdate,
    AchievementOut,
    AchievementListOut,
    AchievementFilter,
    AchievementType,
)

logger = logging.getLogger(__name__)

_ACHIEVEMENT_STORAGE = Path(__file__).resolve().parent.parent / "storage" / "achievements"
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


async def upload_achievement_image(school_id: str, file: UploadFile) -> dict:
    """Save an uploaded image to the achievements storage folder."""
    original = re.sub(r"[^A-Za-z0-9._-]", "_", file.filename or "image")
    ext = Path(original).suffix.lower()
    if ext not in _IMAGE_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Allowed types: JPG, JPEG, PNG, WEBP, GIF")

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(content) > _MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be 10 MB or smaller")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    folder = _ACHIEVEMENT_STORAGE / school_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored_name).write_bytes(content)

    return {"image_url": f"/api/achievements/files/{stored_name}"}


async def _build_achievement_out(data: dict) -> AchievementOut:
    """Build AchievementOut from database row with related data."""
    client = get_client()
    
    # Fetch images
    images_res = (
        await client.table("achievement_images")
        .select("*")
        .eq("achievement_id", data["id"])
        .execute()
    )
    images = images_res.data if images_res.data else []
    
    # Fetch attachments
    attachments_res = (
        await client.table("achievement_attachments")
        .select("*")
        .eq("achievement_id", data["id"])
        .execute()
    )
    attachments = attachments_res.data if attachments_res.data else []
    
    # Fetch assignments
    assignments_res = (
        await client.table("achievement_assignments")
        .select("*")
        .eq("achievement_id", data["id"])
        .execute()
    )
    assignments = assignments_res.data if assignments_res.data else []
    
    return AchievementOut(
        id=data["id"],
        school_id=data["school_id"],
        title=data["title"],
        description=data["description"],
        type=data["type"],
        category=data.get("category"),
        level=data.get("level"),
        achievement_date=data.get("achievement_date"),
        cover_image=data.get("cover_image"),
        pinned=data.get("pinned", False),
        created_by=data["created_by"],
        created_at=data["created_at"],
        updated_at=data["updated_at"],
        images=images,
        attachments=attachments,
        assignments=assignments,
        assigned_count=len(assignments),
    )


async def create_achievement(
    school_id: str,
    body: AchievementCreate,
    created_by: str,
) -> AchievementOut:
    """Create a new achievement."""
    client = get_client()
    
    # Create achievement
    achievement_data = {
        "school_id": school_id,
        "title": body.title,
        "description": body.description,
        "type": body.type.value,
        "category": body.category.value if body.category else None,
        "level": body.level.value if body.level else None,
        "achievement_date": body.achievement_date.isoformat() if body.achievement_date else None,
        "cover_image": body.cover_image,
        "created_by": created_by,
    }
    
    try:
        res = await client.table("achievements").insert(achievement_data).execute()
    except APIError as e:
        logger.error("Failed to create achievement: %s", e)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create achievement")
    
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create achievement")
    
    achievement = res.data[0]
    achievement_id = achievement["id"]
    
    # Add images
    if body.images:
        for image_url in body.images:
            await client.table("achievement_images").insert({
                "achievement_id": achievement_id,
                "image_url": image_url,
            }).execute()
    
    # Add attachments
    if body.attachments:
        for attachment in body.attachments:
            await client.table("achievement_attachments").insert({
                "achievement_id": achievement_id,
                "file_url": attachment["file_url"],
                "file_name": attachment.get("file_name"),
                "file_type": attachment["file_type"],
            }).execute()
    
    # Add student assignments
    if body.type == AchievementType.STUDENT and body.assigned_student_ids:
        for student_id in body.assigned_student_ids:
            await client.table("achievement_assignments").insert({
                "achievement_id": achievement_id,
                "user_type": "student",
                "user_id": student_id,
            }).execute()
    
    # Add teacher assignments
    if body.type == AchievementType.TEACHER and body.assigned_teacher_ids:
        for teacher_id in body.assigned_teacher_ids:
            await client.table("achievement_assignments").insert({
                "achievement_id": achievement_id,
                "user_type": "teacher",
                "user_id": teacher_id,
            }).execute()
    
    return await _build_achievement_out(achievement)


async def update_achievement(
    school_id: str,
    achievement_id: str,
    body: AchievementUpdate,
) -> AchievementOut:
    """Update an existing achievement."""
    client = get_client()
    
    # Check if achievement exists and belongs to school
    res = (
        await client.table("achievements")
        .select("*")
        .eq("id", achievement_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achievement not found")
    
    # Update achievement
    update_data = {
        "title": body.title,
        "description": body.description,
        "type": body.type.value,
        "category": body.category.value if body.category else None,
        "level": body.level.value if body.level else None,
        "achievement_date": body.achievement_date.isoformat() if body.achievement_date else None,
        "cover_image": body.cover_image,
    }
    
    try:
        await client.table("achievements").update(update_data).eq("id", achievement_id).execute()
    except APIError as e:
        logger.error("Failed to update achievement: %s", e)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update achievement")
    
    # Delete existing images and add new ones
    await client.table("achievement_images").delete().eq("achievement_id", achievement_id).execute()
    if body.images:
        for image_url in body.images:
            await client.table("achievement_images").insert({
                "achievement_id": achievement_id,
                "image_url": image_url,
            }).execute()
    
    # Delete existing attachments and add new ones
    await client.table("achievement_attachments").delete().eq("achievement_id", achievement_id).execute()
    if body.attachments:
        for attachment in body.attachments:
            await client.table("achievement_attachments").insert({
                "achievement_id": achievement_id,
                "file_url": attachment["file_url"],
                "file_name": attachment.get("file_name"),
                "file_type": attachment["file_type"],
            }).execute()
    
    # Delete existing assignments and add new ones
    await client.table("achievement_assignments").delete().eq("achievement_id", achievement_id).execute()
    
    if body.type == AchievementType.STUDENT and body.assigned_student_ids:
        for student_id in body.assigned_student_ids:
            await client.table("achievement_assignments").insert({
                "achievement_id": achievement_id,
                "user_type": "student",
                "user_id": student_id,
            }).execute()
    
    if body.type == AchievementType.TEACHER and body.assigned_teacher_ids:
        for teacher_id in body.assigned_teacher_ids:
            await client.table("achievement_assignments").insert({
                "achievement_id": achievement_id,
                "user_type": "teacher",
                "user_id": teacher_id,
            }).execute()
    
    # Fetch updated achievement
    updated_res = (
        await client.table("achievements")
        .select("*")
        .eq("id", achievement_id)
        .limit(1)
        .execute()
    )
    
    return await _build_achievement_out(updated_res.data[0])


async def toggle_pin(school_id: str, achievement_id: str) -> AchievementOut:
    """Toggle the pinned status of an achievement."""
    client = get_client()

    res = (
        await client.table("achievements")
        .select("*")
        .eq("id", achievement_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )

    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achievement not found")

    current_pinned = res.data[0].get("pinned", False)
    await client.table("achievements").update({"pinned": not current_pinned}).eq("id", achievement_id).execute()

    updated_res = (
        await client.table("achievements")
        .select("*")
        .eq("id", achievement_id)
        .limit(1)
        .execute()
    )
    return await _build_achievement_out(updated_res.data[0])


async def delete_achievement(school_id: str, achievement_id: str) -> None:
    """Delete an achievement."""
    client = get_client()
    
    # Check if achievement exists and belongs to school
    res = (
        await client.table("achievements")
        .select("id")
        .eq("id", achievement_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achievement not found")
    
    # Delete achievement (cascade will handle related records)
    await client.table("achievements").delete().eq("id", achievement_id).execute()


async def get_achievement(school_id: str, achievement_id: str) -> AchievementOut:
    """Get a single achievement by ID."""
    client = get_client()
    
    res = (
        await client.table("achievements")
        .select("*")
        .eq("id", achievement_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Achievement not found")
    
    return await _build_achievement_out(res.data[0])


async def list_achievements(
    school_id: str,
    user_id: Optional[str] = None,
    user_role: Optional[str] = None,
    filter: Optional[AchievementFilter] = None,
    page: int = 1,
    page_size: int = 20,
) -> AchievementListOut:
    """List achievements with filtering and pagination."""
    client = get_client()
    
    achievements = []
    total = 0
    
    # Base query for school achievements
    query = client.table("achievements").select("*", count="exact").eq("school_id", school_id)
    
    # Apply type filter if provided
    if filter and filter.type:
        query = query.eq("type", filter.type.value)
    
    # Apply category filter if provided
    if filter and filter.category:
        query = query.eq("category", filter.category.value)
    
    # Apply level filter if provided
    if filter and filter.level:
        query = query.eq("level", filter.level.value)
    
    # Apply search filter if provided
    if filter and filter.search:
        query = query.ilike("title", f"%{filter.search}%")
    
    # For students and teachers, also fetch their assigned achievements
    if user_role in ["student", "teacher"] and user_id:
        # Fetch school achievements (only if type is not filtered or is 'school')
        school_query = client.table("achievements").select("*", count="exact").eq("school_id", school_id)
        if filter and filter.type and filter.type != AchievementType.SCHOOL:
            school_query = school_query.eq("type", filter.type.value)
        else:
            school_query = school_query.eq("type", "school")
        
        if filter and filter.category:
            school_query = school_query.eq("category", filter.category.value)
        if filter and filter.level:
            school_query = school_query.eq("level", filter.level.value)
        if filter and filter.search:
            school_query = school_query.ilike("title", f"%{filter.search}%")
        
        school_res = await school_query.execute()
        
        # Fetch assigned achievements
        assigned_res = (
            await client.table("achievement_assignments")
            .select("achievement_id")
            .eq("user_type", user_role)
            .eq("user_id", user_id)
            .execute()
        )
        
        assigned_ids = [a["achievement_id"] for a in assigned_res.data] if assigned_res.data else []
        
        if assigned_ids:
            assigned_query = client.table("achievements").select("*", count="exact").eq("school_id", school_id).in_("id", assigned_ids)
            if filter and filter.category:
                assigned_query = assigned_query.eq("category", filter.category.value)
            if filter and filter.level:
                assigned_query = assigned_query.eq("level", filter.level.value)
            if filter and filter.search:
                assigned_query = assigned_query.ilike("title", f"%{filter.search}%")
            
            assigned_res = await assigned_query.execute()
            achievements = school_res.data + assigned_res.data
            total = (school_res.count or 0) + (assigned_res.count or 0)
        else:
            achievements = school_res.data
            total = school_res.count or 0
    else:
        # Admins see all achievements – pinned first, then by created_at desc
        res = await query.order("pinned", desc=True).order("created_at", desc=True).range(
            (page - 1) * page_size, page * page_size - 1
        ).execute()
        
        achievements = res.data
        total = res.count or 0
    
    # Apply pagination for student/teacher results
    if user_role in ["student", "teacher"] and user_id:
        start_idx = (page - 1) * page_size
        end_idx = page * page_size
        achievements = achievements[start_idx:end_idx]
    
    # Build achievement objects (simplified to avoid too many queries)
    achievement_list = []
    for achievement in achievements:
        try:
            achievement_list.append(await _build_achievement_out(achievement))
        except Exception as e:
            logger.error(f"Failed to build achievement {achievement.get('id')}: {e}")
    
    return AchievementListOut(
        achievements=achievement_list,
        total=total,
        page=page,
        page_size=page_size,
    )

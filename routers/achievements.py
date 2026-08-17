from fastapi import APIRouter, Depends, HTTPException, status, Query, File, UploadFile
from fastapi.responses import FileResponse
from typing import Optional
from pathlib import Path

from schemas.achievements import (
    AchievementCreate,
    AchievementUpdate,
    AchievementOut,
    AchievementListOut,
    AchievementFilter,
)
from services.achievement_service import (
    create_achievement,
    update_achievement,
    delete_achievement,
    get_achievement,
    list_achievements,
    upload_achievement_image,
    toggle_pin,
)
from utils.deps import require_roles

router = APIRouter(prefix="/achievements", tags=["achievements"])


@router.post("/upload-image")
async def upload_image_endpoint(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles("school_admin", "office_staff", "principal", "vice_principal")),
) -> dict:
    """Upload an image for an achievement."""
    return await upload_achievement_image(user["school_id"], file)


@router.post("", response_model=AchievementOut, status_code=status.HTTP_201_CREATED)
async def create_achievement_endpoint(
    body: AchievementCreate,
    user: dict = Depends(require_roles("school_admin", "office_staff", "principal", "vice_principal")),
) -> AchievementOut:
    """Create a new achievement."""
    return await create_achievement(user["school_id"], body, user["id"])


@router.get("", response_model=AchievementListOut)
async def list_achievements_endpoint(
    type: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_roles("school_admin", "office_staff", "principal", "vice_principal", "teacher", "student")),
) -> AchievementListOut:
    """List achievements with filtering and pagination."""
    from schemas.achievements import AchievementType, AchievementCategory, AchievementLevel
    
    filter_obj = None
    if type or category or level or year or month or search:
        filter_obj = AchievementFilter(
            type=AchievementType(type) if type else None,
            category=AchievementCategory(category) if category else None,
            level=AchievementLevel(level) if level else None,
            year=year,
            month=month,
            search=search,
        )
    
    return await list_achievements(
        school_id=user["school_id"],
        user_id=user["id"],
        user_role=user["role"],
        filter=filter_obj,
        page=page,
        page_size=page_size,
    )


@router.get("/{achievement_id}", response_model=AchievementOut)
async def get_achievement_endpoint(
    achievement_id: str,
    user: dict = Depends(require_roles("school_admin", "office_staff", "principal", "vice_principal", "teacher", "student")),
) -> AchievementOut:
    """Get a single achievement by ID."""
    return await get_achievement(user["school_id"], achievement_id)


@router.put("/{achievement_id}", response_model=AchievementOut)
async def update_achievement_endpoint(
    achievement_id: str,
    body: AchievementUpdate,
    user: dict = Depends(require_roles("school_admin", "office_staff", "principal", "vice_principal")),
) -> AchievementOut:
    """Update an existing achievement."""
    return await update_achievement(user["school_id"], achievement_id, body)


@router.delete("/{achievement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_achievement_endpoint(
    achievement_id: str,
    user: dict = Depends(require_roles("school_admin", "office_staff", "principal", "vice_principal")),
) -> None:
    """Delete an achievement."""
    await delete_achievement(user["school_id"], achievement_id)


@router.patch("/{achievement_id}/pin", response_model=AchievementOut)
async def toggle_pin_endpoint(
    achievement_id: str,
    user: dict = Depends(require_roles("school_admin", "office_staff", "principal", "vice_principal")),
) -> AchievementOut:
    """Toggle the pinned status of an achievement."""
    return await toggle_pin(user["school_id"], achievement_id)


_MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@router.get("/files/{filename}")
async def get_achievement_file(filename: str) -> FileResponse:
    """Serve an uploaded achievement image."""
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    storage = Path(__file__).resolve().parent.parent / "storage" / "achievements"
    found = None
    for sub in storage.iterdir():
        candidate = sub / safe
        if candidate.is_file():
            found = candidate
            break
    if not found:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    ext = found.suffix.lower()
    return FileResponse(found, media_type=_MIME_BY_EXT.get(ext, "application/octet-stream"), filename=safe)

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Response, status

from schemas.library import (
    LibraryBookDetailOut,
    LibraryBookRequestIn,
    LibraryBookSummaryOut,
    LibraryCategoryOut,
    LibraryFilter,
    LibraryHistoryItemOut,
    LibraryIssueOut,
    LibraryRenewalRequestIn,
    LibraryRequestOut,
    LibrarySchoolStatsOut,
    LibrarySummaryOut,
)
from services import library_service
from utils.deps import require_roles

router = APIRouter(prefix="/library", tags=["library"])


@router.get("/summary", response_model=LibrarySummaryOut)
async def library_summary(user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal"))) -> LibrarySummaryOut:
    return await library_service.get_summary(user["school_id"], user["id"])


@router.get("/school-stats", response_model=LibrarySchoolStatsOut)
async def school_stats(user: dict = Depends(require_roles("school_admin", "principal", "vice_principal"))) -> LibrarySchoolStatsOut:
    return await library_service.get_school_stats(user["school_id"])


@router.get("/categories", response_model=List[LibraryCategoryOut])
async def library_categories(user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal"))) -> List[LibraryCategoryOut]:
    return await library_service.list_categories(user["school_id"])


@router.get("/books", response_model=List[LibraryBookSummaryOut])
async def search_books(
    q: str = "",
    title: str = "",
    author: str = "",
    subject: str = "",
    category: str = "",
    isbn: str = "",
    publisher: str = "",
    filter: Optional[LibraryFilter] = None,
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> List[LibraryBookSummaryOut]:
    return await library_service.list_books(
        user["school_id"],
        user["id"],
        q=q,
        title=title,
        author=author,
        subject=subject,
        category=category,
        isbn=isbn,
        publisher=publisher,
        filter_value=filter,
    )


@router.get("/books/{book_id}", response_model=LibraryBookDetailOut)
async def book_details(
    book_id: str,
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> LibraryBookDetailOut:
    return await library_service.get_book_detail(user["school_id"], user["id"], book_id)


@router.post("/books/{book_id}/request", response_model=LibraryRequestOut)
async def request_book(
    book_id: str,
    body: LibraryBookRequestIn,
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> LibraryRequestOut:
    return await library_service.request_book(
        user["school_id"],
        user["id"],
        book_id,
        note=body.note,
    )


@router.get("/issues/current", response_model=List[LibraryIssueOut])
async def current_issues(user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal"))) -> List[LibraryIssueOut]:
    return await library_service.list_current_issues(user["school_id"], user["id"])


@router.post("/issues/{issue_id}/renewal-request", response_model=LibraryRequestOut)
async def request_renewal(
    issue_id: str,
    body: LibraryRenewalRequestIn,
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> LibraryRequestOut:
    return await library_service.request_renewal(
        user["school_id"],
        user["id"],
        issue_id,
        note=body.note,
    )


@router.get("/issues/history", response_model=List[LibraryHistoryItemOut])
async def issue_history(
    q: str = "",
    year: Optional[int] = None,
    subject: str = "",
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> List[LibraryHistoryItemOut]:
    return await library_service.list_issue_history(
        user["school_id"],
        user["id"],
        q=q,
        year=year,
        subject=subject,
    )


@router.get("/requests", response_model=List[LibraryRequestOut])
async def my_requests(user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal"))) -> List[LibraryRequestOut]:
    return await library_service.list_requests(user["school_id"], user["id"])


@router.post("/requests/{request_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_request(
    request_id: str,
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> Response:
    await library_service.cancel_request(user["school_id"], user["id"], request_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/favorites", response_model=List[LibraryBookSummaryOut])
async def favorites(user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal"))) -> List[LibraryBookSummaryOut]:
    return await library_service.list_favorites(user["school_id"], user["id"])


@router.post("/favorites/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_favorite(
    book_id: str,
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> Response:
    await library_service.add_favorite(user["school_id"], user["id"], book_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/favorites/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    book_id: str,
    user: dict = Depends(require_roles("teacher", "school_admin", "principal", "vice_principal")),
) -> Response:
    await library_service.remove_favorite(user["school_id"], user["id"], book_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

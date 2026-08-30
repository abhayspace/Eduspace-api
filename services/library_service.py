from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from typing import Iterable, List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.library import (
    LibraryBookDetailOut,
    LibraryBookSummaryOut,
    LibraryCategoryOut,
    LibraryDuesOut,
    LibraryDueRecordIn,
    LibraryDueRecordOut,
    LibraryFilter,
    LibraryHistoryItemOut,
    LibraryIssueOut,
    LibraryRequestOut,
    LibrarySchoolStatsOut,
    LibrarySummaryOut,
)

BOOK_COLUMNS = (
    "id,school_id,title,author,subject,category,isbn,publisher,edition,language,"
    "shelf_number,cover_image_url,description,total_copies,is_digital,"
    "digital_resource_url,digital_resource_format,popularity_score,is_active,"
    "created_at,updated_at"
)
ISSUE_COLUMNS = (
    "id,school_id,book_id,issued_to_user_id,issue_date,due_date,return_date,"
    "renewed_count,created_at,updated_at"
)
REQUEST_COLUMNS = (
    "id,school_id,book_id,requester_user_id,issue_id,request_type,status,note,"
    "requested_at,decided_at,cancelled_at"
)
DEFAULT_CATEGORIES = [
    "Science",
    "Mathematics",
    "English",
    "Computer",
    "Social Science",
    "Commerce",
    "Literature",
    "Competitive Exams",
    "Reference Books",
    "Magazines",
]


def _parse_date(value: object) -> Optional[date]:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_datetime(value: object) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    raw = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _norm(value: object) -> str:
    return str(value or "").strip().lower()


def _contains(haystack: object, needle: str) -> bool:
    return needle in _norm(haystack)


def _book_matches(row: dict, *, q: str, title: str, author: str, subject: str, category: str, isbn: str, publisher: str) -> bool:
    if q:
        fields = [
            row.get("title"),
            row.get("author"),
            row.get("subject"),
            row.get("category"),
            row.get("isbn"),
            row.get("publisher"),
        ]
        if not any(_contains(value, q) for value in fields):
            return False
    if title and not _contains(row.get("title"), title):
        return False
    if author and not _contains(row.get("author"), author):
        return False
    if subject and not _contains(row.get("subject"), subject):
        return False
    if category and not _contains(row.get("category"), category):
        return False
    if isbn and not _contains(row.get("isbn"), isbn):
        return False
    if publisher and not _contains(row.get("publisher"), publisher):
        return False
    return True


async def _get_books_by_ids(school_id: str, book_ids: Iterable[str]) -> dict[str, dict]:
    ids = [book_id for book_id in dict.fromkeys(book_ids) if book_id]
    if not ids:
        return {}
    client = get_client()
    res = (
        await client.table("library_books")
        .select(BOOK_COLUMNS)
        .eq("school_id", school_id)
        .in_("id", ids)
        .execute()
    )
    return {row["id"]: row for row in (res.data or [])}


async def _issue_stats(school_id: str, book_ids: Iterable[str]) -> tuple[dict[str, int], dict[str, date | None]]:
    ids = [book_id for book_id in dict.fromkeys(book_ids) if book_id]
    if not ids:
        return {}, {}
    client = get_client()
    res = (
        await client.table("library_issues")
        .select("book_id,due_date")
        .eq("school_id", school_id)
        .in_("book_id", ids)
        .is_("return_date", "null")
        .execute()
    )
    active_count: dict[str, int] = {}
    next_due: dict[str, date | None] = {}
    for row in res.data or []:
        book_id = row.get("book_id")
        if not book_id:
            continue
        active_count[book_id] = active_count.get(book_id, 0) + 1
        due = _parse_date(row.get("due_date"))
        prev = next_due.get(book_id)
        if due and (prev is None or due < prev):
            next_due[book_id] = due
    return active_count, next_due


async def _favorite_book_ids(school_id: str, user_id: str, book_ids: Iterable[str] | None = None) -> set[str]:
    client = get_client()
    query = (
        client.table("library_favorites")
        .select("book_id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
    )
    ids = [book_id for book_id in dict.fromkeys(book_ids or []) if book_id]
    if ids:
        query = query.in_("book_id", ids)
    res = await query.execute()
    return {row["book_id"] for row in (res.data or []) if row.get("book_id")}


def _book_summary(
    row: dict,
    *,
    active_count: int,
    next_due: Optional[date],
    is_favorite: bool,
) -> LibraryBookSummaryOut:
    total_copies = max(int(row.get("total_copies") or 0), 0)
    available_copies = max(total_copies - active_count, 0)
    return LibraryBookSummaryOut(
        id=row["id"],
        title=row.get("title") or "Untitled Book",
        author=row.get("author") or "",
        subject=row.get("subject") or "",
        category=row.get("category") or "",
        isbn=row.get("isbn") or "",
        publisher=row.get("publisher") or "",
        edition=row.get("edition") or "",
        language=row.get("language") or "",
        shelf_number=row.get("shelf_number") or "",
        cover_image_url=row.get("cover_image_url"),
        total_copies=total_copies,
        available_copies=available_copies,
        availability_status="available" if available_copies > 0 else "issued_out",
        estimated_availability_date=next_due if available_copies == 0 else None,
        is_favorite=is_favorite,
        is_digital=bool(row.get("is_digital")),
        popularity_score=int(row.get("popularity_score") or 0),
        created_at=_parse_datetime(row.get("created_at")),
    )


async def list_categories(school_id: str) -> list[LibraryCategoryOut]:
    client = get_client()
    res = (
        await client.table("library_books")
        .select("category")
        .eq("school_id", school_id)
        .eq("is_active", True)
        .execute()
    )
    counts: dict[str, int] = {}
    for row in res.data or []:
        label = str(row.get("category") or "").strip()
        if not label:
            continue
        counts[label] = counts.get(label, 0) + 1
    ordered = list(DEFAULT_CATEGORIES)
    for label in counts:
        if label not in ordered:
            ordered.append(label)
    return [LibraryCategoryOut(label=label, count=counts.get(label, 0)) for label in ordered]


async def get_summary(school_id: str, user_id: str) -> LibrarySummaryOut:
    client = get_client()
    books_res, current_issues_res, pending_res, favorites_res = await asyncio.gather(
        client.table("library_books")
        .select("id,total_copies")
        .eq("school_id", school_id)
        .eq("is_active", True)
        .execute(),
        client.table("library_issues")
        .select("id")
        .eq("school_id", school_id)
        .eq("issued_to_user_id", user_id)
        .is_("return_date", "null")
        .execute(),
        client.table("library_requests")
        .select("id")
        .eq("school_id", school_id)
        .eq("requester_user_id", user_id)
        .eq("status", "pending_approval")
        .execute(),
        client.table("library_favorites")
        .select("id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .execute(),
    )
    books = books_res.data or []
    active_count, _ = await _issue_stats(school_id, [row["id"] for row in books if row.get("id")])
    available_books = 0
    for row in books:
        total = max(int(row.get("total_copies") or 0), 0)
        if total - active_count.get(row["id"], 0) > 0:
            available_books += 1

    return LibrarySummaryOut(
        available_books=available_books,
        my_current_issues=len(current_issues_res.data or []),
        pending_requests=len(pending_res.data or []),
        favorite_books=len(favorites_res.data or []),
    )


async def list_books(
    school_id: str,
    user_id: str,
    *,
    q: str = "",
    title: str = "",
    author: str = "",
    subject: str = "",
    category: str = "",
    isbn: str = "",
    publisher: str = "",
    filter_value: Optional[LibraryFilter] = None,
) -> list[LibraryBookSummaryOut]:
    client = get_client()
    res = (
        await client.table("library_books")
        .select(BOOK_COLUMNS)
        .eq("school_id", school_id)
        .eq("is_active", True)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    rows = res.data or []
    q = _norm(q)
    title = _norm(title)
    author = _norm(author)
    subject = _norm(subject)
    category = _norm(category)
    isbn = _norm(isbn)
    publisher = _norm(publisher)
    rows = [
        row
        for row in rows
        if _book_matches(
            row,
            q=q,
            title=title,
            author=author,
            subject=subject,
            category=category,
            isbn=isbn,
            publisher=publisher,
        )
    ]

    book_ids = [row["id"] for row in rows if row.get("id")]
    issue_stats_result, favorite_ids = await asyncio.gather(
        _issue_stats(school_id, book_ids),
        _favorite_book_ids(school_id, user_id, book_ids),
    )
    active_count, next_due = issue_stats_result

    items = [
        _book_summary(
            row,
            active_count=active_count.get(row["id"], 0),
            next_due=next_due.get(row["id"]),
            is_favorite=row["id"] in favorite_ids,
        )
        for row in rows
    ]

    if filter_value == "available":
        items = [item for item in items if item.available_copies > 0]
    elif filter_value == "issued_out":
        items = [item for item in items if item.available_copies == 0]
    elif filter_value == "new_arrivals":
        cutoff = date.today().toordinal() - 45
        items = [
            item
            for item in items
            if item.created_at and item.created_at.date().toordinal() >= cutoff
        ]
    elif filter_value == "ebooks":
        items = [item for item in items if item.is_digital]
    elif filter_value == "most_popular":
        items.sort(key=lambda item: (-item.popularity_score, item.title.lower()))
        return items

    items.sort(
        key=lambda item: (
            item.available_copies == 0,
            -(item.created_at.timestamp() if item.created_at else 0),
            item.title.lower(),
        )
    )
    return items


async def get_book_detail(school_id: str, user_id: str, book_id: str) -> LibraryBookDetailOut:
    client = get_client()
    res = (
        await client.table("library_books")
        .select(BOOK_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", book_id)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Book not found")
    row = res.data[0]
    active_count, next_due = await _issue_stats(school_id, [book_id])
    favorite_ids = await _favorite_book_ids(school_id, user_id, [book_id])
    summary = _book_summary(
        row,
        active_count=active_count.get(book_id, 0),
        next_due=next_due.get(book_id),
        is_favorite=book_id in favorite_ids,
    )
    return LibraryBookDetailOut(
        **summary.model_dump(),
        description=row.get("description") or "",
        digital_resource_url=row.get("digital_resource_url"),
        digital_resource_format=row.get("digital_resource_format") or "",
    )


async def request_book(school_id: str, user_id: str, book_id: str, note: str = "") -> LibraryRequestOut:
    await get_book_detail(school_id, user_id, book_id)
    client = get_client()
    existing = (
        await client.table("library_requests")
        .select(REQUEST_COLUMNS)
        .eq("school_id", school_id)
        .eq("requester_user_id", user_id)
        .eq("book_id", book_id)
        .eq("request_type", "book")
        .in_("status", ["pending_approval", "approved", "ready_for_pickup"])
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You already have a {row.get('status', 'pending')} request for this book",
        )

    inserted = (
        await client.table("library_requests")
        .insert(
            {
                "school_id": school_id,
                "book_id": book_id,
                "requester_user_id": user_id,
                "request_type": "book",
                "status": "pending_approval",
                "note": (note or "").strip(),
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to request book")
    return (await list_requests(school_id, user_id, request_type="book", request_ids=[inserted.data[0]["id"]]))[0]


async def add_favorite(school_id: str, user_id: str, book_id: str) -> None:
    await get_book_detail(school_id, user_id, book_id)
    client = get_client()
    await (
        client.table("library_favorites")
        .upsert(
            {
                "school_id": school_id,
                "user_id": user_id,
                "book_id": book_id,
            },
            on_conflict="school_id,user_id,book_id",
        )
        .execute()
    )


async def remove_favorite(school_id: str, user_id: str, book_id: str) -> None:
    client = get_client()
    await (
        client.table("library_favorites")
        .delete()
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .eq("book_id", book_id)
        .execute()
    )


async def list_favorites(school_id: str, user_id: str) -> list[LibraryBookSummaryOut]:
    client = get_client()
    res = (
        await client.table("library_favorites")
        .select("book_id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    book_ids = [row.get("book_id") for row in (res.data or []) if row.get("book_id")]
    if not book_ids:
        return []
    books = await _get_books_by_ids(school_id, book_ids)
    active_count, next_due = await _issue_stats(school_id, book_ids)
    items = [
        _book_summary(
            books[book_id],
            active_count=active_count.get(book_id, 0),
            next_due=next_due.get(book_id),
            is_favorite=True,
        )
        for book_id in book_ids
        if book_id in books and books[book_id].get("is_active", True)
    ]
    return items


async def list_current_issues(school_id: str, user_id: str) -> list[LibraryIssueOut]:
    client = get_client()
    res = (
        await client.table("library_issues")
        .select(ISSUE_COLUMNS)
        .eq("school_id", school_id)
        .eq("issued_to_user_id", user_id)
        .is_("return_date", "null")
        .order("due_date")
        .execute()
    )
    rows = res.data or []
    issue_ids = [row["id"] for row in rows if row.get("id")]
    book_ids = [row["book_id"] for row in rows if row.get("book_id")]
    books = await _get_books_by_ids(school_id, book_ids)
    renewal_res = (
        await client.table("library_requests")
        .select(REQUEST_COLUMNS)
        .eq("school_id", school_id)
        .eq("requester_user_id", user_id)
        .eq("request_type", "renewal")
        .in_("issue_id", issue_ids or ["00000000-0000-0000-0000-000000000000"])
        .order("requested_at", desc=True)
        .execute()
    )
    renewal_status: dict[str, str] = {}
    for row in renewal_res.data or []:
        issue_id = row.get("issue_id")
        if issue_id and issue_id not in renewal_status:
            renewal_status[issue_id] = row.get("status") or "pending_approval"

    today = date.today()
    items: list[LibraryIssueOut] = []
    for row in rows:
        book = books.get(row.get("book_id"))
        if not book:
            continue
        due_date = _parse_date(row.get("due_date")) or today
        items.append(
            LibraryIssueOut(
                id=row["id"],
                book_id=book["id"],
                title=book.get("title") or "Untitled Book",
                author=book.get("author") or "",
                subject=book.get("subject") or "",
                cover_image_url=book.get("cover_image_url"),
                issue_date=_parse_date(row.get("issue_date")) or today,
                return_due_date=due_date,
                return_date=None,
                days_remaining=(due_date - today).days,
                renewal_status=renewal_status.get(row["id"], "not_requested"),  # type: ignore[arg-type]
                renewed_count=int(row.get("renewed_count") or 0),
                is_overdue=due_date < today,
            )
        )
    return items


async def request_renewal(school_id: str, user_id: str, issue_id: str, note: str = "") -> LibraryRequestOut:
    client = get_client()
    issue_res = (
        await client.table("library_issues")
        .select(ISSUE_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", issue_id)
        .eq("issued_to_user_id", user_id)
        .is_("return_date", "null")
        .limit(1)
        .execute()
    )
    if not issue_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Current issue not found")
    issue = issue_res.data[0]
    existing = (
        await client.table("library_requests")
        .select("id")
        .eq("school_id", school_id)
        .eq("requester_user_id", user_id)
        .eq("issue_id", issue_id)
        .eq("request_type", "renewal")
        .eq("status", "pending_approval")
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "Renewal request already pending")
    inserted = (
        await client.table("library_requests")
        .insert(
            {
                "school_id": school_id,
                "book_id": issue["book_id"],
                "requester_user_id": user_id,
                "issue_id": issue_id,
                "request_type": "renewal",
                "status": "pending_approval",
                "note": (note or "").strip(),
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to request renewal")
    return (await list_requests(school_id, user_id, request_ids=[inserted.data[0]["id"]]))[0]


async def list_issue_history(
    school_id: str,
    user_id: str,
    *,
    q: str = "",
    year: Optional[int] = None,
    subject: str = "",
) -> list[LibraryHistoryItemOut]:
    client = get_client()
    res = (
        await client.table("library_issues")
        .select(ISSUE_COLUMNS)
        .eq("school_id", school_id)
        .eq("issued_to_user_id", user_id)
        .not_.is_("return_date", "null")
        .order("return_date", desc=True)
        .execute()
    )
    rows = res.data or []
    books = await _get_books_by_ids(school_id, [row["book_id"] for row in rows if row.get("book_id")])
    q_norm = _norm(q)
    subject_norm = _norm(subject)
    items: list[LibraryHistoryItemOut] = []
    for row in rows:
        book = books.get(row.get("book_id"))
        if not book:
            continue
        issue_date = _parse_date(row.get("issue_date"))
        return_date = _parse_date(row.get("return_date"))
        if not issue_date:
            continue
        if year and return_date and return_date.year != year and issue_date.year != year:
            continue
        if q_norm and not (
            _contains(book.get("title"), q_norm)
            or _contains(book.get("author"), q_norm)
            or _contains(book.get("subject"), q_norm)
        ):
            continue
        if subject_norm and not _contains(book.get("subject"), subject_norm):
            continue
        items.append(
            LibraryHistoryItemOut(
                id=row["id"],
                book_id=book["id"],
                title=book.get("title") or "Untitled Book",
                author=book.get("author") or "",
                subject=book.get("subject") or "",
                issue_date=issue_date,
                return_date=return_date,
                total_days_borrowed=max(((return_date or date.today()) - issue_date).days, 0),
            )
        )
    return items


async def list_requests(
    school_id: str,
    user_id: str,
    *,
    request_type: Optional[str] = None,
    request_ids: Optional[list[str]] = None,
) -> list[LibraryRequestOut]:
    client = get_client()
    query = (
        client.table("library_requests")
        .select(REQUEST_COLUMNS)
        .eq("school_id", school_id)
        .eq("requester_user_id", user_id)
        .order("requested_at", desc=True)
    )
    if request_type:
        query = query.eq("request_type", request_type)
    if request_ids:
        query = query.in_("id", request_ids)
    res = await query.execute()
    rows = res.data or []
    books = await _get_books_by_ids(school_id, [row["book_id"] for row in rows if row.get("book_id")])
    items: list[LibraryRequestOut] = []
    for row in rows:
        book = books.get(row.get("book_id"))
        if not book:
            continue
        requested_at = _parse_datetime(row.get("requested_at")) or datetime.now(timezone.utc)
        items.append(
            LibraryRequestOut(
                id=row["id"],
                book_id=book["id"],
                issue_id=row.get("issue_id"),
                book_name=book.get("title") or "Untitled Book",
                request_type=row.get("request_type") or "book",
                request_date=requested_at,
                status=row.get("status") or "pending_approval",
                note=row.get("note") or "",
            )
        )
    return items


async def cancel_request(school_id: str, user_id: str, request_id: str) -> None:
    client = get_client()
    res = (
        await client.table("library_requests")
        .select(REQUEST_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", request_id)
        .eq("requester_user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    row = res.data[0]
    if row.get("status") != "pending_approval":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only pending requests can be cancelled")
    await (
        client.table("library_requests")
        .update(
            {
                "status": "cancelled",
                "cancelled_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        .eq("school_id", school_id)
        .eq("id", request_id)
        .eq("requester_user_id", user_id)
        .execute()
    )


async def get_school_stats(school_id: str) -> LibrarySchoolStatsOut:
    client = get_client()
    books_res, requests_res, issued_res = await asyncio.gather(
        client.table("library_books")
        .select("id,total_copies")
        .eq("school_id", school_id)
        .eq("is_active", True)
        .execute(),
        client.table("library_requests")
        .select("id")
        .eq("school_id", school_id)
        .eq("status", "pending_approval")
        .execute(),
        client.table("library_issues")
        .select("id")
        .eq("school_id", school_id)
        .is_("return_date", "null")
        .execute(),
    )
    total_books = sum(max(int(row.get("total_copies") or 0), 0) for row in (books_res.data or []))
    total_requests = len(requests_res.data or [])
    current_issued = len(issued_res.data or [])

    return LibrarySchoolStatsOut(
        total_books=total_books,
        total_requests=total_requests,
        current_issued=current_issued,
    )


DUE_RECORD_COLUMNS = "id,school_id,user_id,record_type,amount,note,recorded_at,created_by,created_at"


async def create_due_record(
    school_id: str,
    created_by: str,
    body: LibraryDueRecordIn,
) -> LibraryDueRecordOut:
    client = get_client()
    res = (
        await client.table("library_due_records")
        .insert({
            "school_id": school_id,
            "user_id": body.user_id,
            "record_type": body.record_type,
            "amount": body.amount,
            "note": body.note,
            "recorded_at": body.recorded_at.isoformat(),
            "created_by": created_by,
        })
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create due record")
    return _build_due_record_out(res.data[0])


async def list_user_due_records(school_id: str, user_id: str, limit: int = 5) -> LibraryDuesOut:
    client = get_client()
    res = (
        await client.table("library_due_records")
        .select(DUE_RECORD_COLUMNS)
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .order("recorded_at", desc=True)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    rows = res.data or []
    total_fines = sum(
        float(r.get("amount") or 0) for r in rows if r.get("record_type") == "fine"
    )
    total_deposits = sum(
        float(r.get("amount") or 0) for r in rows if r.get("record_type") == "deposit"
    )
    total_due = max(0.0, total_fines - total_deposits)
    records = [_build_due_record_out(r) for r in rows[:limit]]
    return LibraryDuesOut(total_due=round(total_due, 2), records=records)


def _build_due_record_out(row: dict) -> LibraryDueRecordOut:
    return LibraryDueRecordOut(
        id=row["id"],
        user_id=row["user_id"],
        record_type=row["record_type"],
        amount=float(row.get("amount") or 0),
        note=row.get("note") or "",
        recorded_at=_parse_date(row.get("recorded_at")) or date.today(),
        created_at=_parse_datetime(row.get("created_at")) or datetime.now(timezone.utc),
        created_by=row.get("created_by") or "",
    )

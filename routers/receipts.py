"""Fee receipt APIs — student download + admin search / regenerate."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response

from schemas.receipt import EnsureReceiptIn, EnsureReceiptOut, FeeReceiptListOut, FeeReceiptOut
from services.receipt import receipt_service
from services.receipt.storage import default_storage
from utils.deps import current_user, require_roles

router = APIRouter(tags=["receipts"])

_FEE_ADMIN = require_roles(
    "school_admin",
    "office_staff",
    "principal",
    "vice_principal",
    "super_admin",
)


# ---------------------------------------------------------------------------
# Student
# ---------------------------------------------------------------------------


@router.get("/student/receipts", response_model=FeeReceiptListOut)
async def student_list_receipts(user: dict = Depends(current_user)) -> FeeReceiptListOut:
    items = await receipt_service.list_student_receipts(user)
    return FeeReceiptListOut(items=[FeeReceiptOut(**i) for i in items], total=len(items))


@router.get("/student/receipts/{receipt_id}")
async def student_download_receipt(
    receipt_id: str,
    user: dict = Depends(current_user),
):
    content, filename, _number = await receipt_service.download_receipt_pdf(
        user, receipt_id, as_student=True
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------


@router.get("/admin/receipts", response_model=FeeReceiptListOut)
async def admin_search_receipts(
    user: dict = Depends(_FEE_ADMIN),
    student_name: Optional[str] = Query(None, alias="studentName"),
    admission_no: Optional[str] = Query(None, alias="admissionNo"),
    receipt_number: Optional[str] = Query(None, alias="receiptNumber"),
    class_name: Optional[str] = Query(None, alias="className"),
    date_from: Optional[str] = Query(None, alias="dateFrom"),
    date_to: Optional[str] = Query(None, alias="dateTo"),
    payment_status: Optional[str] = Query(None, alias="paymentStatus"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> FeeReceiptListOut:
    result = await receipt_service.search_admin_receipts(
        user,
        student_name=student_name,
        admission_no=admission_no,
        receipt_number=receipt_number,
        class_name=class_name,
        date_from=date_from,
        date_to=date_to,
        payment_status=payment_status,
        limit=limit,
        offset=offset,
    )
    return FeeReceiptListOut(
        items=[FeeReceiptOut(**i) for i in result["items"]],
        total=result["total"],
    )


@router.post("/admin/receipts/ensure", response_model=EnsureReceiptOut)
async def admin_ensure_receipt(
    body: EnsureReceiptIn,
    user: dict = Depends(_FEE_ADMIN),
) -> EnsureReceiptOut:
    """Create (or return) a PDF receipt for an office or online paid transaction."""
    row = await receipt_service.ensure_receipt_for_transaction(
        user, body.transaction_id
    )
    return EnsureReceiptOut(**row)


@router.get("/admin/receipts/{receipt_id}")
async def admin_download_receipt(
    receipt_id: str,
    user: dict = Depends(_FEE_ADMIN),
):
    content, filename, _number = await receipt_service.download_receipt_pdf(
        user, receipt_id, as_student=False
    )
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/admin/receipts/{receipt_id}/regenerate", response_model=FeeReceiptOut)
async def admin_regenerate_receipt(
    receipt_id: str,
    user: dict = Depends(_FEE_ADMIN),
) -> FeeReceiptOut:
    row = await receipt_service.regenerate_receipt(user, receipt_id)
    return FeeReceiptOut(**row)


# ---------------------------------------------------------------------------
# Authenticated file serve (pdf_url target)
# ---------------------------------------------------------------------------


@router.get("/receipts/files/{year}/{filename}")
async def serve_receipt_file(
    year: str,
    filename: str,
    user: dict = Depends(current_user),
):
    """Serve a stored PDF. Access is re-checked against fee_receipts ownership."""
    safe_name = Path(filename).name
    if safe_name != filename or ".." in year:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid path")

    receipt_number = safe_name.replace(".pdf", "")
    client_user = user
    # Students may only fetch their own; admins scoped to school; super_admin all
    if user.get("role") == "student":
        meta = await receipt_service.get_student_receipt(user, receipt_number)
        _ = meta
    else:
        await receipt_service.get_admin_receipt(client_user, receipt_number)

    relative = f"{year}/{safe_name}"
    try:
        path = default_storage.resolve_local_path(relative)
    except FileNotFoundError:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    except ValueError as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    return FileResponse(path, media_type="application/pdf", filename=safe_name)

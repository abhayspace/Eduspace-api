"""Expense tracker — transactions."""
from typing import List

from fastapi import APIRouter, Depends

from schemas.content import (
    ExpenseTransactionCreateIn,
    ExpenseTransactionOut,
    ExpenseTransactionUpdateIn,
    SavingCreateIn,
    SavingOut,
    SavingUpdateIn,
)
from services import expense_service
from utils.deps import require_roles

router = APIRouter(prefix="/expenses", tags=["expenses"])

_EXPENSE_ROLES = ("school_admin", "principal", "vice_principal", "super_admin", "accountant")


@router.get("/transactions", response_model=List[ExpenseTransactionOut])
async def list_transactions(
    limit: int = 15,
    month: int | None = None,
    year: int | None = None,
    date: str | None = None,
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> List[ExpenseTransactionOut]:
    if date:
        return await expense_service.list_recent_transactions(
            user["school_id"],
            on_date=date,
        )
    if month is not None and year is not None:
        return await expense_service.list_recent_transactions(
            user["school_id"],
            month=month,
            year=year,
        )
    capped = max(1, min(limit, 100))
    return await expense_service.list_recent_transactions(user["school_id"], limit=capped)


@router.post("/transactions", response_model=ExpenseTransactionOut)
async def create_transaction(
    body: ExpenseTransactionCreateIn,
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> ExpenseTransactionOut:
    created_by = user.get("full_name") or user.get("email") or "Admin"
    return await expense_service.create_transaction(user["school_id"], body, created_by)


@router.patch("/transactions/{transaction_id}", response_model=ExpenseTransactionOut)
async def update_transaction(
    transaction_id: str,
    body: ExpenseTransactionUpdateIn,
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> ExpenseTransactionOut:
    return await expense_service.update_transaction(user["school_id"], transaction_id, body)


@router.delete("/transactions/{transaction_id}")
async def delete_transaction(
    transaction_id: str,
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> dict:
    await expense_service.delete_transaction(user["school_id"], transaction_id)
    return {"ok": True}


@router.get("/savings", response_model=List[SavingOut])
async def list_savings(
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> List[SavingOut]:
    return await expense_service.list_savings(user["school_id"])


@router.post("/savings", response_model=SavingOut)
async def create_saving(
    body: SavingCreateIn,
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> SavingOut:
    created_by = user.get("full_name") or user.get("email") or "Admin"
    return await expense_service.create_saving(user["school_id"], body, created_by)


@router.patch("/savings/{saving_id}", response_model=SavingOut)
async def update_saving(
    saving_id: str,
    body: SavingUpdateIn,
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> SavingOut:
    return await expense_service.update_saving(user["school_id"], saving_id, body)


@router.delete("/savings/{saving_id}")
async def delete_saving(
    saving_id: str,
    user: dict = Depends(require_roles(*_EXPENSE_ROLES)),
) -> dict:
    await expense_service.delete_saving(user["school_id"], saving_id)
    return {"ok": True}

"""Budget routes: month view, allocation upsert, copy-from-previous."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import budget as budget_engine
from .. import schemas
from ..deps import get_db, month_path
from ..models import Allocation, Category

router = APIRouter(prefix="/api/budget", tags=["budget"])


def _category_or_404(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found.",
        )
    return category


@router.get("/{month}", response_model=schemas.MonthBudget)
def get_month_budget(
    month: str = Depends(month_path), db: Session = Depends(get_db)
) -> budget_engine.MonthView:
    return budget_engine.month_view(db, month)


@router.put(
    "/{month}/allocations/{category_id}", response_model=schemas.AllocationRead
)
def upsert_allocation(
    category_id: int,
    payload: schemas.AllocationUpsertRequest,
    month: str = Depends(month_path),
    db: Session = Depends(get_db),
) -> Allocation:
    _category_or_404(db, category_id)
    # Atomic upsert: a non-atomic select-then-insert races when two writes for
    # the same not-yet-existing (month, category) arrive together (e.g. rapid
    # keyboard assigning), both insert, and one hits the UNIQUE constraint.
    stmt = sqlite_insert(Allocation).values(
        month=month,
        category_id=category_id,
        amount_cents=payload.amount_cents,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[Allocation.month, Allocation.category_id],
        set_={"amount_cents": payload.amount_cents, "updated_at": func.now()},
    )
    db.execute(stmt)
    db.commit()
    allocation = db.scalar(
        select(Allocation).where(
            Allocation.month == month, Allocation.category_id == category_id
        )
    )
    return allocation


@router.post(
    "/{month}/copy-from-previous", response_model=schemas.CopyFromPreviousResponse
)
def copy_from_previous(
    month: str = Depends(month_path), db: Session = Depends(get_db)
) -> schemas.CopyFromPreviousResponse:
    source_month = budget_engine.previous_month(month)
    source_allocations = list(
        db.scalars(select(Allocation).where(Allocation.month == source_month))
    )
    existing = {
        alloc.category_id: alloc
        for alloc in db.scalars(select(Allocation).where(Allocation.month == month))
    }

    copied = 0
    for alloc in source_allocations:
        target = existing.get(alloc.category_id)
        if target is None:
            db.add(
                Allocation(
                    month=month,
                    category_id=alloc.category_id,
                    amount_cents=alloc.amount_cents,
                )
            )
        else:
            target.amount_cents = alloc.amount_cents
        copied += 1
    db.commit()

    return schemas.CopyFromPreviousResponse(
        month=month, source_month=source_month, copied=copied
    )

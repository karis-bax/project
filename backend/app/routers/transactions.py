"""Transaction routes: filtered + cursor-paginated list, CRUD, bulk categorize."""

from __future__ import annotations

import base64
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from .. import schemas
from ..deps import get_db, validate_month
from ..models import Account, Category, Transaction

router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def _encode_cursor(when: dt.date, txn_id: int) -> str:
    raw = f"{when.isoformat()}|{txn_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def _decode_cursor(cursor: str) -> tuple[dt.date, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        date_str, id_str = raw.split("|")
        return dt.date.fromisoformat(date_str), int(id_str)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="Malformed pagination cursor.",
        ) from exc


def _account_or_404(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found.",
        )
    return account


def _category_or_404(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Category {category_id} not found.",
        )
    return category


def _apply_filters(
    stmt,
    *,
    month: str | None,
    account_id: int | None,
    category_id: int | None,
    q: str | None,
    uncategorized: bool | None,
):
    if month is not None:
        validate_month(month)
        stmt = stmt.where(func.strftime("%Y-%m", Transaction.date) == month)
    if account_id is not None:
        stmt = stmt.where(Transaction.account_id == account_id)
    if category_id is not None:
        stmt = stmt.where(Transaction.category_id == category_id)
    if uncategorized:
        stmt = stmt.where(Transaction.category_id.is_(None))
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(Transaction.payee.ilike(pattern), Transaction.memo.ilike(pattern))
        )
    return stmt


@router.get("/count", response_model=schemas.CountResponse)
def count_transactions(
    month: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    q: str | None = None,
    uncategorized: bool | None = None,
    db: Session = Depends(get_db),
) -> schemas.CountResponse:
    stmt = _apply_filters(
        select(func.count()).select_from(Transaction),
        month=month,
        account_id=account_id,
        category_id=category_id,
        q=q,
        uncategorized=uncategorized,
    )
    return schemas.CountResponse(count=int(db.scalar(stmt) or 0))


@router.get("/payees", response_model=list[schemas.PayeeSuggestion])
def list_payees(db: Session = Depends(get_db)) -> list[schemas.PayeeSuggestion]:
    # Count each (payee, category) pair, then pick the most-frequent category
    # per payee as the suggestion.
    rows = db.execute(
        select(
            Transaction.payee,
            Transaction.category_id,
            func.count().label("n"),
        ).group_by(Transaction.payee, Transaction.category_id)
    ).all()

    totals: dict[str, int] = {}
    best: dict[str, tuple[int, int | None]] = {}  # payee -> (count, category_id)
    for payee, category_id, n in rows:
        totals[payee] = totals.get(payee, 0) + n
        current = best.get(payee)
        if current is None or n > current[0]:
            best[payee] = (n, category_id)

    suggestions = [
        schemas.PayeeSuggestion(
            payee=payee,
            suggested_category_id=best[payee][1],
            count=total,
        )
        for payee, total in totals.items()
    ]
    suggestions.sort(key=lambda s: (-s.count, s.payee.lower()))
    return suggestions


@router.get("", response_model=schemas.TransactionListResponse)
def list_transactions(
    month: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    q: str | None = None,
    uncategorized: bool | None = None,
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = None,
    db: Session = Depends(get_db),
) -> schemas.TransactionListResponse:
    # Eager-load account and category to avoid N+1 when serializing relations.
    stmt = select(Transaction).options(
        joinedload(Transaction.account), joinedload(Transaction.category)
    )
    stmt = _apply_filters(
        stmt,
        month=month,
        account_id=account_id,
        category_id=category_id,
        q=q,
        uncategorized=uncategorized,
    )

    if cursor is not None:
        cur_date, cur_id = _decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Transaction.date < cur_date,
                and_(Transaction.date == cur_date, Transaction.id < cur_id),
            )
        )

    stmt = stmt.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(
        limit + 1
    )
    rows = list(db.scalars(stmt))

    next_cursor: str | None = None
    if len(rows) > limit:
        rows = rows[:limit]
        last = rows[-1]
        next_cursor = _encode_cursor(last.date, last.id)

    return schemas.TransactionListResponse(
        items=[schemas.TransactionWithRelations.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@router.post(
    "",
    response_model=schemas.TransactionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    payload: schemas.TransactionCreate, db: Session = Depends(get_db)
) -> Transaction:
    _account_or_404(db, payload.account_id)
    if payload.category_id is not None:
        _category_or_404(db, payload.category_id)
    txn = Transaction(**payload.model_dump())
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


@router.patch("/{transaction_id}", response_model=schemas.TransactionRead)
def update_transaction(
    transaction_id: int,
    payload: schemas.TransactionUpdate,
    db: Session = Depends(get_db),
) -> Transaction:
    txn = db.get(Transaction, transaction_id)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found.",
        )
    data = payload.model_dump(exclude_unset=True)
    if data.get("account_id") is not None:
        _account_or_404(db, data["account_id"])
    if data.get("category_id") is not None:
        _category_or_404(db, data["category_id"])
    for field, value in data.items():
        setattr(txn, field, value)
    db.commit()
    db.refresh(txn)
    return txn


@router.delete("/{transaction_id}", response_model=schemas.DeletedResponse)
def delete_transaction(
    transaction_id: int, db: Session = Depends(get_db)
) -> schemas.DeletedResponse:
    txn = db.get(Transaction, transaction_id)
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found.",
        )
    db.delete(txn)
    db.commit()
    return schemas.DeletedResponse(id=transaction_id, deleted=True)


@router.post("/bulk-categorize", response_model=schemas.BulkCategorizeResponse)
def bulk_categorize(
    payload: schemas.BulkCategorizeRequest, db: Session = Depends(get_db)
) -> schemas.BulkCategorizeResponse:
    if payload.category_id is not None:
        _category_or_404(db, payload.category_id)
    if not payload.ids:
        return schemas.BulkCategorizeResponse(updated=0)
    result = db.execute(
        update(Transaction)
        .where(Transaction.id.in_(payload.ids))
        .values(category_id=payload.category_id)
    )
    db.commit()
    return schemas.BulkCategorizeResponse(updated=result.rowcount or 0)

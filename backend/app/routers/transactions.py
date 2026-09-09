"""Transaction routes: filtered + cursor-paginated list, CRUD, bulk categorize."""

from __future__ import annotations

import base64
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from .. import schemas
from ..deps import get_db, get_live_or_404, validate_month
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
    return get_live_or_404(db, Account, account_id, label="Account")


def _category_or_404(db: Session, category_id: int) -> Category:
    return get_live_or_404(db, Category, category_id, label="Category")


def _apply_filters(
    stmt,
    *,
    month: str | None,
    account_id: int | None,
    category_id: int | None,
    q: str | None,
    uncategorized: bool | None,
    pending: bool | None = None,
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
    if pending is not None:
        stmt = stmt.where(Transaction.pending.is_(pending))
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
    pending: bool | None = None,
    db: Session = Depends(get_db),
) -> schemas.CountResponse:
    stmt = _apply_filters(
        select(func.count()).select_from(Transaction),
        month=month,
        account_id=account_id,
        category_id=category_id,
        q=q,
        uncategorized=uncategorized,
        pending=pending,
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
    pending: bool | None = None,
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
        pending=pending,
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
    txn = get_live_or_404(db, Transaction, transaction_id, label="Transaction")
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
    # get_live_or_404 excludes already-deleted rows, so a second DELETE is a
    # 404 and cannot re-stamp deleted_at. Re-stamping would reset the retention
    # clock that scripts/purge_soft_deleted.py reads, keeping a row alive
    # indefinitely.
    txn = get_live_or_404(db, Transaction, transaction_id, label="Transaction")
    # Soft delete: an undo safety net. The row keeps its constraints so a later
    # re-import/resync can revive it; it vanishes from every read path.
    txn.deleted_at = dt.datetime.now()
    db.commit()
    return schemas.DeletedResponse(id=transaction_id, deleted=True)


@router.post("/{transaction_id}/restore", response_model=schemas.TransactionRead)
def restore_transaction(
    transaction_id: int, db: Session = Depends(get_db)
) -> Transaction:
    # Must look past the soft-delete filter to find the row to restore.
    txn = db.scalar(
        select(Transaction)
        .where(Transaction.id == transaction_id)
        .execution_options(include_deleted=True)
    )
    if txn is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transaction {transaction_id} not found.",
        )
    txn.deleted_at = None
    db.commit()
    db.refresh(txn)
    return txn


@router.post("/bulk-categorize", response_model=schemas.BulkCategorizeResponse)
def bulk_categorize(
    payload: schemas.BulkCategorizeRequest, db: Session = Depends(get_db)
) -> schemas.BulkCategorizeResponse:
    if payload.category_id is not None:
        _category_or_404(db, payload.category_id)
    if not payload.ids:
        return schemas.BulkCategorizeResponse(updated=0)
    # Loaded and modified through the ORM rather than a bulk UPDATE so the
    # session-level filters apply. `updated` is therefore rows actually
    # changed: ids that are soft-deleted (or, later, not the caller's) are
    # silently not counted, which is the honest number.
    rows = list(db.scalars(select(Transaction).where(Transaction.id.in_(payload.ids))))
    for txn in rows:
        txn.category_id = payload.category_id
    db.commit()
    return schemas.BulkCategorizeResponse(updated=len(rows))

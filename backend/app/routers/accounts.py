"""Account routes. Deleting an account archives it (never a hard delete)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..models import Account

router = APIRouter(prefix="/api/accounts", tags=["accounts"])


@router.get("", response_model=list[schemas.AccountRead])
def list_accounts(
    include_archived: bool = False, db: Session = Depends(get_db)
) -> list[Account]:
    stmt = select(Account).order_by(Account.name)
    if not include_archived:
        stmt = stmt.where(Account.archived.is_(False))
    return list(db.scalars(stmt))


@router.post("", response_model=schemas.AccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: schemas.AccountCreate, db: Session = Depends(get_db)
) -> Account:
    account = Account(**payload.model_dump())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _get_or_404(db: Session, account_id: int) -> Account:
    account = db.get(Account, account_id)
    if account is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Account {account_id} not found.",
        )
    return account


@router.patch("/{account_id}", response_model=schemas.AccountRead)
def update_account(
    account_id: int,
    payload: schemas.AccountUpdate,
    db: Session = Depends(get_db),
) -> Account:
    account = _get_or_404(db, account_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(account, field, value)
    db.commit()
    db.refresh(account)
    return account


@router.delete("/{account_id}", response_model=schemas.AccountRead)
def archive_account(
    account_id: int, db: Session = Depends(get_db)
) -> Account:
    account = _get_or_404(db, account_id)
    account.archived = True
    db.commit()
    db.refresh(account)
    return account

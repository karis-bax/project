"""Bank sync endpoints (SimpleFIN today, provider-agnostic underneath)."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..models import Account, SyncRun, Transaction
from ..sync import credentials, service
from ..sync.base import SyncError
from ..sync.simplefin import SetupTokenError, claim_setup_token

router = APIRouter(prefix="/api/sync", tags=["sync"])


def _computed_balance(db: Session, account_id: int) -> int:
    opening = db.scalar(
        select(Account.opening_balance_cents).where(Account.id == account_id)
    )
    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0)).where(
            Transaction.account_id == account_id
        )
    )
    return int(opening or 0) + int(total or 0)


def _statuses(db: Session) -> list[schemas.SyncAccountStatus]:
    linked = {
        a.external_id: a
        for a in db.scalars(
            select(Account).where(Account.sync_source == "simplefin")
        )
        if a.external_id
    }
    discovered = service.discovered()

    external_ids = set(discovered) | set(linked)
    rows: list[schemas.SyncAccountStatus] = []
    for external_id in sorted(external_ids):
        disc = discovered.get(external_id)
        local = linked.get(external_id)
        reported = disc.balance_cents if disc else None
        computed = _computed_balance(db, local.id) if local else None
        mismatch = (
            reported is not None and computed is not None and reported != computed
        )
        rows.append(
            schemas.SyncAccountStatus(
                external_id=external_id,
                name=disc.name if disc else (local.name if local else external_id),
                org_name=disc.org_name if disc else "",
                currency=disc.currency if disc else "USD",
                reported_balance_cents=reported,
                balance_date=disc.balance_date.isoformat()
                if disc and disc.balance_date
                else None,
                linked_account_id=local.id if local else None,
                local_account_name=local.name if local else None,
                computed_balance_cents=computed,
                last_synced_at=local.last_synced_at if local else None,
                mismatch=mismatch,
            )
        )
    return rows


def _run_to_schema(run: SyncRun) -> schemas.SyncRunRead:
    return schemas.SyncRunRead(
        id=run.id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        status=run.status.value,
        accounts_synced=run.accounts_synced,
        added=run.added,
        updated=run.updated,
        errors=run.errors or [],
    )


@router.post("/claim", response_model=list[schemas.SyncAccountStatus])
def claim(
    payload: schemas.SyncClaimRequest, db: Session = Depends(get_db)
) -> list[schemas.SyncAccountStatus]:
    # One-time claim — never retried. Store the access URL, then discover.
    try:
        access_url = claim_setup_token(payload.setup_token)
    except SetupTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from None
    credentials.store_access_url(access_url)

    provider = service.build_provider()
    if provider is None:  # pragma: no cover - store just succeeded
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Access URL was not stored.",
        )
    now = datetime.now()
    try:
        accounts = provider.fetch(now.date() - timedelta(days=30), now.date() + timedelta(days=1))
    except SyncError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from None
    service.cache_accounts(accounts)
    return _statuses(db)


@router.get("/accounts", response_model=list[schemas.SyncAccountStatus])
def list_sync_accounts(db: Session = Depends(get_db)) -> list[schemas.SyncAccountStatus]:
    return _statuses(db)


@router.post("/link", response_model=list[schemas.SyncAccountStatus])
def link_account(
    payload: schemas.SyncLinkRequest, db: Session = Depends(get_db)
) -> list[schemas.SyncAccountStatus]:
    if payload.account_id is None and payload.create_as is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either account_id or create_as.",
        )

    # Ensure no other local account already claims this external id.
    prior = db.scalar(
        select(Account).where(
            Account.sync_source == "simplefin",
            Account.external_id == payload.external_id,
        )
    )
    if prior is not None:
        prior.sync_source = None
        prior.external_id = None

    if payload.create_as is not None:
        account = Account(
            name=payload.create_as.name,
            kind=payload.create_as.kind,
            opening_balance_cents=0,
            archived=False,
            sync_source="simplefin",
            external_id=payload.external_id,
        )
        db.add(account)
    else:
        account = db.get(Account, payload.account_id)
        if account is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Account {payload.account_id} not found.",
            )
        account.sync_source = "simplefin"
        account.external_id = payload.external_id

    db.commit()
    return _statuses(db)


@router.post("/run", response_model=schemas.SyncRunRead)
def run(
    payload: schemas.SyncRunRequest, db: Session = Depends(get_db)
) -> schemas.SyncRunRead:
    provider = service.build_provider()
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Not connected to a bank. Claim a setup token first.",
        )
    run_row = service.run_sync(db, provider, days=payload.days)
    return _run_to_schema(run_row)


@router.get("/runs", response_model=list[schemas.SyncRunRead])
def list_runs(db: Session = Depends(get_db)) -> list[schemas.SyncRunRead]:
    runs = db.scalars(
        select(SyncRun).order_by(SyncRun.started_at.desc(), SyncRun.id.desc()).limit(20)
    )
    return [_run_to_schema(r) for r in runs]

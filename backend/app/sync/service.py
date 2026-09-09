"""Sync orchestration: window selection, run recording, discovered cache.

Provider-agnostic: everything here talks to the ``SyncProvider`` protocol, so
tests inject a fake provider built from recorded JSON — no live calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import SyncRun, SyncStatus
from . import credentials, engine
from .base import NormalizedAccount, SyncError, SyncProvider
from .simplefin import SimpleFINProvider


class SyncInProgress(Exception):
    """Raised when a sync is requested while another run holds the lock."""


@dataclass
class Discovered:
    external_id: str
    name: str
    org_name: str
    currency: str
    balance_cents: int
    balance_date: date | None


# Cached view of the most recently discovered external accounts (single user,
# process lifetime). Refreshed on claim and on every run. Holds reported
# balances so reconciliation does not require a live call on every page load.
_DISCOVERED: dict[str, Discovered] = {}


def cache_accounts(accounts: list[NormalizedAccount]) -> None:
    for a in accounts:
        _DISCOVERED[a.external_id] = Discovered(
            external_id=a.external_id,
            name=a.name,
            org_name=a.org_name,
            currency=a.currency,
            balance_cents=a.balance_cents,
            balance_date=a.balance_date,
        )


def discovered() -> dict[str, Discovered]:
    return dict(_DISCOVERED)


def build_provider() -> SimpleFINProvider | None:
    url = credentials.get_access_url()
    return SimpleFINProvider(url) if url else None


def run_sync(
    db: Session,
    provider: SyncProvider,
    days: int = 30,
    now: datetime | None = None,
) -> SyncRun:
    """Fetch an overlapping window and upsert, recording a SyncRun.

    Never raises on a provider fetch error or on errlist entries — both are
    surfaced via the returned SyncRun so the UI can display them.
    """

    now = now or datetime.now()
    since = now.date() - timedelta(days=days)  # overlapping window, not "since last"
    until = now.date() + timedelta(days=1)

    # Acquire the run lock: a running SyncRun row. The partial unique index on
    # status='running' rejects a second concurrent run.
    run = SyncRun(
        status=SyncStatus.running,
        started_at=now,
        accounts_synced=0,
        added=0,
        updated=0,
        errors=[],
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Record the blocked attempt so it isn't invisible, then signal 409.
        db.add(
            SyncRun(
                status=SyncStatus.failed,
                started_at=now,
                finished_at=datetime.now(),
                errors=[{"message": "A sync is already running."}],
            )
        )
        db.commit()
        raise SyncInProgress("A sync is already running.") from None
    run_id = run.id

    try:
        accounts = provider.fetch(since, until)
        errlist = list(getattr(provider, "errlist", []) or [])
        result = engine.apply(db, accounts, now=now)
        cache_accounts(accounts)
        run.status = SyncStatus.partial if errlist else SyncStatus.ok
        run.accounts_synced = result.accounts_synced
        run.added = result.added
        run.updated = result.updated
        run.swept_count = result.deleted
        run.errors = errlist
        run.finished_at = datetime.now()
        db.commit()
    except Exception as exc:  # noqa: BLE001 - always record a failed run
        db.rollback()
        # The running row was committed (lock); flip it to failed to release it.
        run = db.get(SyncRun, run_id)
        run.status = SyncStatus.failed
        run.finished_at = datetime.now()
        run.errors = [{"message": credentials.redact(exc)}]
        db.commit()

    db.refresh(run)
    return run

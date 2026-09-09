"""Sync orchestration: window selection, run recording, discovered cache.

Provider-agnostic: everything here talks to the ``SyncProvider`` protocol, so
tests inject a fake provider built from recorded JSON — no live calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from ..models import SyncRun, SyncStatus
from . import credentials, engine
from .base import NormalizedAccount, SyncError, SyncProvider
from .simplefin import SimpleFINProvider


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

    try:
        accounts = provider.fetch(since, until)
    except SyncError as exc:
        run = SyncRun(
            status=SyncStatus.failed,
            started_at=now,
            finished_at=datetime.now(),
            accounts_synced=0,
            added=0,
            updated=0,
            errors=[{"message": str(exc)}],
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    errlist = list(getattr(provider, "errlist", []) or [])
    result = engine.apply(db, accounts, now=now)
    cache_accounts(accounts)

    run = SyncRun(
        status=SyncStatus.partial if errlist else SyncStatus.ok,
        started_at=now,
        finished_at=datetime.now(),
        accounts_synced=result.accounts_synced,
        added=result.added,
        updated=result.updated,
        errors=errlist,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run

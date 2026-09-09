"""Bank-sync tests. Recorded JSON fixtures only — no live SimpleFIN calls."""

from __future__ import annotations

import json
import traceback
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import importer  # noqa: F401 - ensures models import path is warm
from app.db import Base
from app.models import Account, AccountKind, Transaction, TxnSource
from app.sync import credentials, engine, service, simplefin
from app.sync.base import NormalizedAccount, NormalizedTxn, SyncError

FIXTURE = Path(__file__).parent / "fixtures" / "simplefin_accountset.json"


@pytest.fixture
def db() -> Session:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    session = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)()
    try:
        yield session
    finally:
        session.close()
        eng.dispose()


def make_synced_account(db: Session, external_id: str = "ACT-1") -> Account:
    account = Account(
        name="Checking",
        kind=AccountKind.checking,
        opening_balance_cents=0,
        archived=False,
        sync_source="simplefin",
        external_id=external_id,
    )
    db.add(account)
    db.commit()
    return account


class FakeProvider:
    """A SyncProvider built from recorded data — never touches the network."""

    def __init__(self, accounts: list[NormalizedAccount], errlist: list | None = None):
        self._accounts = accounts
        self.errlist = errlist or []

    def fetch(self, since: date, until: date) -> list[NormalizedAccount]:
        return self._accounts


class RaisingProvider:
    errlist: list = []

    def fetch(self, since: date, until: date) -> list[NormalizedAccount]:
        raise SyncError("Failed to fetch from SimpleFIN: ***")


# --- amount parsing (the float trap) ---------------------------------------


def test_amount_to_cents() -> None:
    assert simplefin.amount_to_cents("-33.45") == -3345
    assert simplefin.amount_to_cents("1234.5") == 123450


def test_summing_stays_exact() -> None:
    # The whole point: Decimal keeps 0.1 + 0.2 exact; float would not.
    assert simplefin.amount_to_cents("0.1") + simplefin.amount_to_cents("0.2") == 30
    assert Decimal("0.1") + Decimal("0.2") == Decimal("0.3")


# --- parsing a recorded AccountSet -----------------------------------------


def test_parse_account_set_fixture() -> None:
    data = json.loads(FIXTURE.read_text())
    accounts, errlist = simplefin.parse_account_set(data)
    assert errlist == []
    assert len(accounts) == 1
    acct = accounts[0]
    assert acct.external_id == "ACT-1"
    assert acct.balance_cents == 123450  # "1234.5"
    assert acct.transactions[0].amount_cents == -5230
    assert acct.transactions[1].description == "ACME, INC PAYROLL"


def _accounts_from_fixture() -> list[NormalizedAccount]:
    return simplefin.parse_account_set(json.loads(FIXTURE.read_text()))[0]


# --- upsert idempotence ----------------------------------------------------


def test_resync_identical_payload_adds_zero(db: Session) -> None:
    make_synced_account(db)
    first = engine.apply(db, _accounts_from_fixture())
    db.commit()
    assert first.added == 2
    assert first.updated == 0

    second = engine.apply(db, _accounts_from_fixture())
    db.commit()
    assert second.added == 0
    assert second.updated == 2  # same rows, updated in place — not duplicated

    total = db.scalar(select(func.count()).select_from(Transaction))
    assert total == 2


# --- pending -> posted (the hard case) -------------------------------------


def test_pending_posting_with_changed_id_updates_one_row_keeps_category(
    db: Session,
) -> None:
    account = make_synced_account(db)
    today = date.today()

    # First sync: a $40 pending gas hold.
    pending = NormalizedAccount(
        external_id="ACT-1",
        name="Checking",
        org_name="Test Bank",
        currency="USD",
        balance_cents=0,
        balance_date=today,
        transactions=[
            NormalizedTxn(
                external_id="P1",
                posted_date=today - timedelta(days=2),
                amount_cents=-4000,
                description="SHELL OIL 12345",
                pending=True,
            )
        ],
    )
    engine.apply(db, [pending])
    db.commit()

    # User assigns a category to that pending row.
    row = db.scalar(select(Transaction).where(Transaction.account_id == account.id))
    row.category_id = None  # ensure no rule; then set a real category
    from app.models import Category, CategoryGroup

    group = CategoryGroup(name="Transportation", sort_order=0)
    db.add(group)
    db.flush()
    gas = Category(group_id=group.id, name="Gas", sort_order=0, archived=False)
    db.add(gas)
    db.flush()
    row.category_id = gas.id
    db.commit()

    # Second sync: it posts under a NEW id and a CHANGED amount ($43.17).
    posted = NormalizedAccount(
        external_id="ACT-1",
        name="Checking",
        org_name="Test Bank",
        currency="USD",
        balance_cents=0,
        balance_date=today,
        transactions=[
            NormalizedTxn(
                external_id="X9",
                posted_date=today,
                amount_cents=-4317,
                description="SHELL OIL 12345",
                pending=False,
            )
        ],
    )
    result = engine.apply(db, [posted])
    db.commit()

    assert result.added == 0  # no duplicate created
    assert result.updated == 1

    rows = list(
        db.scalars(select(Transaction).where(Transaction.account_id == account.id))
    )
    assert len(rows) == 1  # still exactly one row
    updated = rows[0]
    assert updated.amount_cents == -4317
    assert updated.pending is False
    assert updated.external_id == "X9"
    assert updated.category_id == gas.id  # category preserved


# --- stale pending cleanup -------------------------------------------------


def test_stale_pending_removed_after_14_days(db: Session) -> None:
    account = make_synced_account(db)
    stale = Transaction(
        account_id=account.id,
        external_id="OLD-PENDING",
        date=date.today() - timedelta(days=20),
        payee="LINGERING HOLD",
        amount_cents=-2500,
        memo="",
        cleared=False,
        pending=True,
        source=TxnSource.sync,
    )
    db.add(stale)
    db.commit()

    # A sync that no longer includes that pending row removes it.
    empty = NormalizedAccount(
        external_id="ACT-1",
        name="Checking",
        org_name="Test Bank",
        currency="USD",
        balance_cents=0,
        balance_date=date.today(),
        transactions=[],
    )
    result = engine.apply(db, [empty])
    db.commit()

    assert result.deleted == 1
    assert db.scalar(select(func.count()).select_from(Transaction)) == 0


# --- errlist surfaces, does not raise --------------------------------------


def test_errlist_surfaces_to_caller(db: Session) -> None:
    make_synced_account(db)
    provider = FakeProvider(
        _accounts_from_fixture(),
        errlist=["Connection to Test Bank needs re-authentication."],
    )
    run = service.run_sync(db, provider)
    assert run.status.value == "partial"
    assert run.errors == ["Connection to Test Bank needs re-authentication."]
    assert run.added == 2


def test_fetch_failure_records_failed_run_without_raising(db: Session) -> None:
    run = service.run_sync(db, RaisingProvider())
    assert run.status.value == "failed"
    assert run.errors  # message present


# --- credential redaction --------------------------------------------------

_SECRET_URL = "https://user:secretpass@bridge.simplefin.org/simplefin"


def test_redact_scrubs_access_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLEFIN_ACCESS_URL", _SECRET_URL)
    text = f"boom talking to {_SECRET_URL}/accounts"
    redacted = credentials.redact(text)
    assert _SECRET_URL not in redacted
    assert "secretpass" not in redacted


def test_access_url_never_in_formatted_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLEFIN_ACCESS_URL", _SECRET_URL)

    def boom(access_url, path, params):
        raise RuntimeError(f"connection refused to {access_url}{path}")

    monkeypatch.setattr(simplefin, "_http_get_json", boom)

    provider = simplefin.SimpleFINProvider(_SECRET_URL)
    try:
        provider.fetch(date.today() - timedelta(days=30), date.today())
    except SyncError:
        formatted = traceback.format_exc()
    else:  # pragma: no cover
        raise AssertionError("expected SyncError")

    assert _SECRET_URL not in formatted
    assert "secretpass" not in formatted

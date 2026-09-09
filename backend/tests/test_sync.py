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
from app.models import (
    Account,
    AccountKind,
    SyncRun,
    SyncStatus,
    Transaction,
    TxnSource,
)
from app.sync import credentials, engine, service, simplefin
from app.sync.base import NormalizedAccount, NormalizedTxn, SyncError

FIXTURE = Path(__file__).parent / "fixtures" / "simplefin_accountset.json"


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


# --- reconciliation (bank vs ledger) ---------------------------------------


def test_reconciliation_reported_vs_computed(db: Session, monkeypatch) -> None:
    from app.routers import sync as sync_router

    account = make_synced_account(db)
    # A ledger that sums to -5230.
    db.add(
        Transaction(
            account_id=account.id,
            external_id="T1",
            date=date.today(),
            payee="PUBLIX",
            amount_cents=-5230,
            memo="",
            source=TxnSource.sync,
        )
    )
    db.commit()

    # Bank reports the same balance -> reconciled (no mismatch).
    monkeypatch.setattr(
        service,
        "_DISCOVERED",
        {
            "ACT-1": service.Discovered(
                external_id="ACT-1",
                name="Checking",
                org_name="Test Bank",
                currency="USD",
                balance_cents=-5230,
                balance_date=date.today(),
            )
        },
    )
    [row] = sync_router._statuses(db)
    assert row.reported_balance_cents == -5230
    assert row.computed_balance_cents == -5230
    assert row.mismatch is False

    # Bank reports a different balance -> mismatch flagged.
    service._DISCOVERED["ACT-1"].balance_cents = -9999
    [row2] = sync_router._statuses(db)
    assert row2.mismatch is True


# --- credential redaction --------------------------------------------------

_SECRET_URL = "https://user:secretpass@bridge.simplefin.org/simplefin"


def test_redact_scrubs_access_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIMPLEFIN_ACCESS_URL", _SECRET_URL)
    text = f"boom talking to {_SECRET_URL}/accounts"
    redacted = credentials.redact(text)
    assert _SECRET_URL not in redacted
    assert "secretpass" not in redacted


def test_setup_token_decode_rejects_bad_input() -> None:
    import base64

    from app.sync.simplefin import SetupTokenError, decode_setup_token

    # Not base64 at all.
    with pytest.raises(SetupTokenError):
        decode_setup_token("!!! not base64 !!!")
    # Valid base64, but not UTF-8.
    with pytest.raises(SetupTokenError):
        decode_setup_token(base64.b64encode(b"\xff\xfe").decode())
    # Valid UTF-8, but not a URL.
    with pytest.raises(SetupTokenError):
        decode_setup_token(base64.b64encode(b"hello there").decode())
    # A real URL decodes fine.
    good = base64.b64encode(b"https://bridge.simplefin.org/claim/abc").decode()
    assert decode_setup_token(good) == "https://bridge.simplefin.org/claim/abc"


def _txn_count(db: Session) -> int:
    from sqlalchemy import func, select

    return db.scalar(select(func.count()).select_from(Transaction))


def _posted(external_id: str, when: date, cents: int, desc: str) -> NormalizedTxn:
    return NormalizedTxn(
        external_id=external_id,
        posted_date=when,
        amount_cents=cents,
        description=desc,
        pending=False,
    )


def _one_account(txns: list[NormalizedTxn]) -> list[NormalizedAccount]:
    return [
        NormalizedAccount(
            external_id="ACT-1",
            name="Checking",
            org_name="Test Bank",
            currency="USD",
            balance_cents=0,
            balance_date=date.today(),
            transactions=txns,
        )
    ]


# --- F2: posted dedup by count matching ------------------------------------


def test_posted_reissued_id_does_not_duplicate(db: Session) -> None:
    make_synced_account(db)
    today = date.today()

    engine.apply(db, _one_account([_posted("OLD", today, -500, "COFFEE SHOP")]))
    db.commit()
    assert _txn_count(db) == 1

    # Same content, DIFFERENT external_id (a reissued id).
    result = engine.apply(db, _one_account([_posted("NEW", today, -500, "COFFEE SHOP")]))
    db.commit()
    assert result.added == 0
    rows = list(db.scalars(__import__("sqlalchemy").select(Transaction)))
    assert len(rows) == 1
    assert rows[0].external_id == "NEW"  # existing row adopted the new id


def test_two_identical_charges_both_survive(db: Session) -> None:
    make_synced_account(db)
    today = date.today()
    payload = _one_account(
        [_posted("C1", today, -500, "COFFEE SHOP"), _posted("C2", today, -500, "COFFEE SHOP")]
    )

    first = engine.apply(db, payload)
    db.commit()
    assert first.added == 2
    assert _txn_count(db) == 2  # two genuine identical charges both survive

    second = engine.apply(db, payload)
    db.commit()
    assert second.added == 0
    assert _txn_count(db) == 2  # resync leaves exactly two, not four or one


def test_count_matching_inserts_only_the_difference(db: Session) -> None:
    make_synced_account(db)
    today = date.today()
    engine.apply(db, _one_account([_posted("OLD", today, -500, "COFFEE SHOP")]))
    db.commit()

    # Payload has 3 of the key with fresh ids; DB has 1 -> insert exactly 2.
    result = engine.apply(
        db,
        _one_account(
            [
                _posted("N1", today, -500, "COFFEE SHOP"),
                _posted("N2", today, -500, "COFFEE SHOP"),
                _posted("N3", today, -500, "COFFEE SHOP"),
            ]
        ),
    )
    db.commit()
    assert result.added == 2
    assert _txn_count(db) == 3


# --- F3: run lock + guarded commit -----------------------------------------


def test_run_records_ok_and_releases_lock(db: Session) -> None:
    make_synced_account(db)
    run = service.run_sync(db, FakeProvider(_accounts_from_fixture()))
    assert run.status.value == "ok"
    running = db.scalar(
        __import__("sqlalchemy").select(__import__("sqlalchemy").func.count())
        .select_from(SyncRun)
        .where(SyncRun.status == SyncStatus.running)
    )
    assert running == 0  # lock released


def test_concurrent_run_is_locked_and_both_recorded(db: Session) -> None:
    make_synced_account(db)
    # Simulate an in-flight run holding the lock.
    inflight = SyncRun(status=SyncStatus.running, started_at=datetime.now(), errors=[])
    db.add(inflight)
    db.commit()

    with pytest.raises(service.SyncInProgress):
        service.run_sync(db, FakeProvider(_accounts_from_fixture()))

    runs = list(db.scalars(__import__("sqlalchemy").select(SyncRun)))
    statuses = {r.status.value for r in runs}
    assert "running" in statuses  # the in-flight one
    assert "failed" in statuses  # the blocked attempt was still recorded


# --- F9: constant query count on sync accounts -----------------------------


def test_statuses_query_count_is_constant(db: Session) -> None:
    from sqlalchemy import event

    from app.routers import sync as sync_router

    db.add(
        Account(
            name="A1", kind=AccountKind.checking, opening_balance_cents=0,
            archived=False, sync_source="simplefin", external_id="E1",
        )
    )
    db.commit()

    engine_bind = db.get_bind()
    count = {"n": 0}

    def _on_exec(*_args):
        count["n"] += 1

    event.listen(engine_bind, "before_cursor_execute", _on_exec)
    try:
        count["n"] = 0
        sync_router._statuses(db)
        one_account = count["n"]

        db.add_all(
            [
                Account(
                    name="A2", kind=AccountKind.savings, opening_balance_cents=0,
                    archived=False, sync_source="simplefin", external_id="E2",
                ),
                Account(
                    name="A3", kind=AccountKind.credit, opening_balance_cents=0,
                    archived=False, sync_source="simplefin", external_id="E3",
                ),
            ]
        )
        db.commit()

        count["n"] = 0
        sync_router._statuses(db)
        three_accounts = count["n"]
    finally:
        event.remove(engine_bind, "before_cursor_execute", _on_exec)

    assert one_account == three_accounts  # no N+1


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

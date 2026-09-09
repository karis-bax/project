"""Soft-delete: a deleted transaction must vanish from EVERY read path, the
route-coverage guard must fail on an uncovered new route, and a matching
re-import/resync must revive rather than duplicate or skip.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.importer import compute_import_hash
from app.insights import current_month
from app.main import app
from app.models import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    Transaction,
    TxnSource,
)
from app.sync import engine as sync_engine
from app.sync.base import NormalizedAccount, NormalizedTxn


@pytest.fixture
def session() -> Session:
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    db = sessionmaker(bind=eng, expire_on_commit=False, class_=Session)()
    try:
        yield db
    finally:
        db.close()
        eng.dispose()


@pytest.fixture
def client(session: Session) -> TestClient:
    def _override():
        yield session

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _setup(session: Session):
    month = current_month()
    year, mon = int(month[:4]), int(month[5:7])
    account = Account(
        name="Checking",
        kind=AccountKind.checking,
        opening_balance_cents=0,
        archived=False,
        sync_source="simplefin",
        external_id="EXT-A",
    )
    group = CategoryGroup(name="Food", sort_order=0)
    session.add_all([account, group])
    session.flush()
    category = Category(group_id=group.id, name="Groceries", sort_order=0, archived=False)
    session.add(category)
    session.flush()
    expense = Transaction(
        account_id=account.id,
        category_id=category.id,
        date=date(year, mon, 10),
        payee="SOLE PAYEE",
        amount_cents=-5000,
        source=TxnSource.manual,
    )
    income = Transaction(
        account_id=account.id,
        category_id=None,
        date=date(year, mon, 1),
        payee="Employer",
        amount_cents=30000,
        source=TxnSource.manual,
    )
    session.add_all([expense, income])
    session.commit()
    return account, category, expense, income, month


def test_soft_delete_vanishes_from_every_read_path(
    client: TestClient, session: Session
) -> None:
    account, category, expense, income, month = _setup(session)

    def txn_ids() -> set[int]:
        body = client.get("/api/transactions").json()
        return {t["id"] for t in body["items"]}

    def category_spend() -> int:
        body = client.get(f"/api/insights/by-category?month={month}").json()
        for g in body["groups"]:
            for c in g["categories"]:
                if c["id"] == category.id:
                    return c["spent_cents"]
        return 0

    def computed_balance() -> int:
        for row in client.get("/api/sync/accounts").json():
            if row["linked_account_id"] == account.id:
                return row["computed_balance_cents"]
        return 0

    # --- Before: both transactions are visible everywhere.
    assert {expense.id, income.id} <= txn_ids()
    assert client.get("/api/transactions/count").json()["count"] == 2
    before = client.get(f"/api/budget/{month}").json()
    cat_before = next(
        c for g in before["groups"] for c in g["categories"] if c["id"] == category.id
    )
    assert cat_before["activity_cents"] == -5000
    assert before["income_cents"] == 30000
    assert before["left_to_assign_cents"] == 30000
    assert category_spend() == 5000
    assert computed_balance() == 25000  # 0 opening + (-5000 + 30000)
    assert "SOLE PAYEE" in {p["payee"] for p in client.get("/api/transactions/payees").json()}
    assert client.get(f"/api/insights/burn?month={month}").status_code == 200
    assert client.get("/api/insights/trends?months=3").status_code == 200
    assert client.get("/api/insights/recurring").status_code == 200

    # --- Soft-delete both.
    assert client.delete(f"/api/transactions/{expense.id}").status_code == 200
    assert client.delete(f"/api/transactions/{income.id}").status_code == 200

    # --- After: gone from every read path.
    assert txn_ids().isdisjoint({expense.id, income.id})
    assert client.get("/api/transactions/count").json()["count"] == 0

    after = client.get(f"/api/budget/{month}").json()
    cat_after = next(
        (c for g in after["groups"] for c in g["categories"] if c["id"] == category.id),
        None,
    )
    assert cat_after is None or cat_after["activity_cents"] == 0  # activity
    assert after["income_cents"] == 0  # income
    assert after["left_to_assign_cents"] == 0  # left_to_assign
    assert category_spend() == 0  # insights by-category
    assert computed_balance() == 0  # sync reconciliation computed balance
    assert "SOLE PAYEE" not in {
        p["payee"] for p in client.get("/api/transactions/payees").json()
    }
    # Pure budget functions also exclude it.
    from app import budget

    assert budget.activity(session, category, month) == 0
    assert budget.available(session, category, month) == 0
    assert budget.income(session, month) == 0
    assert budget.left_to_assign(session, month) == 0

    # Raw row still exists (soft, not hard, delete).
    raw = session.scalar(
        select(func.count())
        .select_from(Transaction)
        .execution_options(include_deleted=True)
    )
    assert raw == 2


# --- runtime route coverage -------------------------------------------------

# GET routes that read transaction data — each is exercised by the vanish test.
_COVERED = {
    "/api/transactions",
    "/api/transactions/count",
    "/api/transactions/payees",
    "/api/budget/{month}",
    "/api/insights/by-category",
    "/api/insights/trends",
    "/api/insights/burn",
    "/api/insights/recurring",
    "/api/sync/accounts",
}
# GET routes that do NOT read transaction data.
_NON_TXN = {
    "/api/health",
    "/api/accounts",
    "/api/categories",
    "/api/goals",
    "/api/rules",
    "/api/sync/runs",
}


def _api_get_paths() -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        path = getattr(route, "path", "")
        if "GET" in methods and path.startswith("/api/"):
            paths.add(path)
    return paths


def test_every_transaction_reading_route_is_covered() -> None:
    classified = _COVERED | _NON_TXN
    unclassified = _api_get_paths() - classified
    assert not unclassified, (
        "New GET /api route(s) not classified for soft-delete coverage: "
        f"{sorted(unclassified)}. Add each to _COVERED (and exercise it in the "
        "vanish test) or to _NON_TXN."
    )


# --- revive on re-import / resync ------------------------------------------


def test_csv_reimport_revives_soft_deleted_row(
    client: TestClient, session: Session
) -> None:
    account = Account(
        name="Checking", kind=AccountKind.checking, opening_balance_cents=0, archived=False
    )
    session.add(account)
    session.commit()

    csv = "Date,Description,Amount\n2026-01-15,PUBLIX,-52.30\n"
    preview = client.post(
        "/api/import/preview",
        data={"account_id": str(account.id)},
        files={"file": ("bank.csv", csv, "text/csv")},
    ).json()
    rows = [
        {
            "date": r["date"],
            "payee": r["payee"],
            "amount_cents": r["amount_cents"],
            "memo": r["memo"],
            "category_id": None,
            "is_duplicate": False,
        }
        for r in preview["rows"]
        if r["importable"]
    ]
    first = client.post(
        "/api/import/commit",
        json={"token": preview["token"], "rows": rows, "skip_duplicates": True},
    ).json()
    assert first["imported"] == 1
    txn = session.scalar(select(Transaction))
    txn_id = txn.id

    # User deletes it.
    client.delete(f"/api/transactions/{txn_id}")
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0

    # Re-importing the same row REVIVES it — same id, not a duplicate.
    preview2 = client.post(
        "/api/import/preview",
        data={"account_id": str(account.id)},
        files={"file": ("bank.csv", csv, "text/csv")},
    ).json()
    rows2 = [
        {
            "date": r["date"],
            "payee": r["payee"],
            "amount_cents": r["amount_cents"],
            "memo": r["memo"],
            "category_id": None,
            "is_duplicate": r["is_duplicate"],
        }
        for r in preview2["rows"]
        if r["importable"]
    ]
    second = client.post(
        "/api/import/commit",
        json={"token": preview2["token"], "rows": rows2, "skip_duplicates": True},
    ).json()
    assert second["imported"] == 1  # revived, not skipped
    total = session.scalar(
        select(func.count()).select_from(Transaction).execution_options(
            include_deleted=True
        )
    )
    assert total == 1  # no duplicate row
    revived = session.get(Transaction, txn_id)
    assert revived is not None and revived.deleted_at is None


def test_resync_revives_soft_deleted_row(session: Session) -> None:
    account = Account(
        name="Checking",
        kind=AccountKind.checking,
        opening_balance_cents=0,
        archived=False,
        sync_source="simplefin",
        external_id="ACT-1",
    )
    session.add(account)
    session.commit()

    payload = [
        NormalizedAccount(
            external_id="ACT-1",
            name="Checking",
            org_name="Bank",
            currency="USD",
            balance_cents=0,
            balance_date=date.today(),
            transactions=[
                NormalizedTxn(
                    external_id="T1",
                    posted_date=date.today(),
                    amount_cents=-5230,
                    description="PUBLIX",
                    pending=False,
                )
            ],
        )
    ]
    sync_engine.apply(session, payload)
    session.commit()
    txn = session.scalar(select(Transaction))
    txn_id = txn.id

    # Soft-delete it, then resync the same transaction.
    txn.deleted_at = datetime.now()
    session.commit()
    assert session.scalar(select(func.count()).select_from(Transaction)) == 0

    result = sync_engine.apply(session, payload)
    session.commit()
    assert result.added == 0  # revived via id match, not inserted
    total = session.scalar(
        select(func.count()).select_from(Transaction).execution_options(
            include_deleted=True
        )
    )
    assert total == 1
    revived = session.get(Transaction, txn_id)
    assert revived is not None and revived.deleted_at is None

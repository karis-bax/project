"""API tests: a happy path and a failure case per route group.

Each test uses a fresh in-memory SQLite database wired in via a ``get_db``
dependency override.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import (
    Account,
    AccountKind,
    Allocation,
    Category,
    CategoryGroup,
    Transaction,
)


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def client(session: Session) -> TestClient:
    def _override_get_db():
        yield session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def seed_basics(session: Session) -> tuple[Account, CategoryGroup, Category]:
    account = Account(
        name="Checking", kind=AccountKind.checking, opening_balance_cents=0, archived=False
    )
    group = CategoryGroup(name="Food", sort_order=0)
    session.add_all([account, group])
    session.flush()
    category = Category(group_id=group.id, name="Groceries", sort_order=0, archived=False)
    session.add(category)
    session.commit()
    return account, group, category


# --- health ----------------------------------------------------------------


def test_health_ok(client: TestClient) -> None:
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_health_wrong_method(client: TestClient) -> None:
    assert client.post("/api/health").status_code == 405


# --- accounts --------------------------------------------------------------


def test_accounts_crud_happy_path(client: TestClient) -> None:
    created = client.post(
        "/api/accounts",
        json={"name": "Savings", "kind": "savings", "opening_balance_cents": 50000},
    )
    assert created.status_code == 201
    account_id = created.json()["id"]

    listing = client.get("/api/accounts")
    assert listing.status_code == 200
    assert any(a["id"] == account_id for a in listing.json())

    patched = client.patch(f"/api/accounts/{account_id}", json={"name": "Rainy Day"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Rainy Day"

    deleted = client.delete(f"/api/accounts/{account_id}")
    assert deleted.status_code == 200
    assert deleted.json()["archived"] is True
    # Archived accounts are hidden from the default listing.
    assert all(a["id"] != account_id for a in client.get("/api/accounts").json())


def test_accounts_patch_missing_is_404(client: TestClient) -> None:
    assert client.patch("/api/accounts/9999", json={"name": "X"}).status_code == 404


# --- categories & groups ---------------------------------------------------


def test_categories_happy_path(client: TestClient) -> None:
    group = client.post("/api/category-groups", json={"name": "Housing", "sort_order": 0})
    assert group.status_code == 201
    group_id = group.json()["id"]

    category = client.post(
        "/api/categories", json={"group_id": group_id, "name": "Mortgage"}
    )
    assert category.status_code == 201
    category_id = category.json()["id"]

    nested = client.get("/api/categories")
    assert nested.status_code == 200
    groups = {g["id"]: g for g in nested.json()}
    assert group_id in groups
    assert any(c["id"] == category_id for c in groups[group_id]["categories"])

    second = client.post("/api/category-groups", json={"name": "Fun", "sort_order": 1})
    reorder = client.patch(
        "/api/category-groups/reorder",
        json={"group_ids": [second.json()["id"], group_id]},
    )
    assert reorder.status_code == 200
    assert [g["id"] for g in reorder.json()] == [second.json()["id"], group_id]


def test_create_category_bad_group_is_404(client: TestClient) -> None:
    resp = client.post("/api/categories", json={"group_id": 4242, "name": "Ghost"})
    assert resp.status_code == 404


def test_delete_category_with_transactions_conflicts(
    client: TestClient, session: Session
) -> None:
    account, group, category = seed_basics(session)
    other = Category(group_id=group.id, name="Dining", sort_order=1, archived=False)
    session.add(other)
    session.flush()
    session.add(
        Transaction(
            account_id=account.id,
            category_id=category.id,
            date=date(2026, 1, 5),
            payee="Publix",
            amount_cents=-5000,
        )
    )
    session.commit()

    # 409 names the transaction count.
    conflict = client.delete(f"/api/categories/{category.id}")
    assert conflict.status_code == 409
    assert "1 transaction" in conflict.json()["detail"]

    # The escape hatch reassigns then archives.
    ok = client.delete(f"/api/categories/{category.id}?reassign_to={other.id}")
    assert ok.status_code == 200
    assert ok.json()["archived"] is True
    moved = client.get(f"/api/transactions?category_id={other.id}")
    assert len(moved.json()["items"]) == 1


# --- transactions ----------------------------------------------------------


def test_transactions_list_pagination_happy_path(
    client: TestClient, session: Session
) -> None:
    account, _group, category = seed_basics(session)
    for day in (1, 2, 3):
        session.add(
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(2026, 1, day),
                payee=f"Store {day}",
                amount_cents=-1000 * day,
            )
        )
    session.commit()

    created = client.post(
        "/api/transactions",
        json={
            "account_id": account.id,
            "category_id": category.id,
            "date": "2026-01-04",
            "payee": "Costco",
            "amount_cents": -9000,
        },
    )
    assert created.status_code == 201

    page1 = client.get("/api/transactions?limit=2")
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    # Ordered date DESC: newest (Jan 4) first, with nested account eager-loaded.
    assert body1["items"][0]["date"] == "2026-01-04"
    assert body1["items"][0]["account"]["id"] == account.id
    assert body1["next_cursor"]

    page2 = client.get(f"/api/transactions?limit=2&cursor={body1['next_cursor']}")
    body2 = page2.json()
    assert [i["date"] for i in body2["items"]] == ["2026-01-02", "2026-01-01"]
    assert body2["next_cursor"] is None

    # Uncategorized + search filters.
    session.add(
        Transaction(
            account_id=account.id,
            category_id=None,
            date=date(2026, 1, 10),
            payee="Employer Payroll",
            amount_cents=300000,
        )
    )
    session.commit()
    unc = client.get("/api/transactions?uncategorized=true")
    assert len(unc.json()["items"]) == 1
    search = client.get("/api/transactions?q=payroll")
    assert len(search.json()["items"]) == 1


def test_transactions_bad_month_is_422(client: TestClient) -> None:
    assert client.get("/api/transactions?month=2026-13").status_code == 422


def test_bulk_categorize_bad_category_is_404(
    client: TestClient, session: Session
) -> None:
    account, _group, _category = seed_basics(session)
    txn = Transaction(
        account_id=account.id,
        category_id=None,
        date=date(2026, 1, 1),
        payee="X",
        amount_cents=-100,
    )
    session.add(txn)
    session.commit()
    resp = client.post(
        "/api/transactions/bulk-categorize",
        json={"ids": [txn.id], "category_id": 9999},
    )
    assert resp.status_code == 404


def test_bulk_categorize_happy_path(client: TestClient, session: Session) -> None:
    account, _group, category = seed_basics(session)
    txn = Transaction(
        account_id=account.id,
        category_id=None,
        date=date(2026, 1, 1),
        payee="X",
        amount_cents=-100,
    )
    session.add(txn)
    session.commit()
    resp = client.post(
        "/api/transactions/bulk-categorize",
        json={"ids": [txn.id], "category_id": category.id},
    )
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1


# --- budget ----------------------------------------------------------------


def test_budget_happy_path(client: TestClient, session: Session) -> None:
    account, _group, category = seed_basics(session)
    session.add(
        Transaction(
            account_id=account.id,
            category_id=None,
            date=date(2026, 1, 1),
            payee="Payroll",
            amount_cents=300000,
        )
    )
    session.commit()

    view = client.get("/api/budget/2026-01")
    assert view.status_code == 200
    body = view.json()
    assert body["month"] == "2026-01"
    assert body["income_cents"] == 300000
    assert any(g["name"] == "Food" for g in body["groups"])

    alloc = client.put(
        f"/api/budget/2026-01/allocations/{category.id}",
        json={"amount_cents": 25000},
    )
    assert alloc.status_code == 200
    assert alloc.json()["amount_cents"] == 25000

    # left_to_assign now reflects the assignment.
    after = client.get("/api/budget/2026-01").json()
    assert after["assigned_cents"] == 25000
    assert after["left_to_assign_cents"] == 275000

    copy = client.post("/api/budget/2026-02/copy-from-previous")
    assert copy.status_code == 200
    assert copy.json() == {"month": "2026-02", "source_month": "2026-01", "copied": 1}
    feb = client.get("/api/budget/2026-02").json()
    assert feb["assigned_cents"] == 25000


def test_budget_bad_month_is_422(client: TestClient) -> None:
    assert client.get("/api/budget/2026-13").status_code == 422

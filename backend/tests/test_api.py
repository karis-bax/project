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
    Goal,
    GoalKind,
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


def test_delete_category_with_available_balance_conflicts(
    client: TestClient, session: Session
) -> None:
    account, _group, category = seed_basics(session)
    # Spending with no allocation leaves a non-zero (overspent) available.
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

    # 409 names the available balance, and nothing is discarded silently.
    conflict = client.delete(f"/api/categories/{category.id}")
    assert conflict.status_code == 409
    assert "50.00" in conflict.json()["detail"]

    # The explicit write-off escape hatch archives it.
    ok = client.delete(f"/api/categories/{category.id}?discard=true")
    assert ok.status_code == 200
    assert ok.json()["archived"] is True
    # Transactions stay put (history preserved), not reassigned.
    assert (
        len(client.get(f"/api/transactions?category_id={category.id}").json()["items"])
        == 1
    )


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


def test_transactions_pending_filter(client: TestClient, session: Session) -> None:
    account, _group, category = seed_basics(session)
    session.add_all(
        [
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(2026, 1, 3),
                payee="Shell",
                amount_cents=-4000,
                pending=True,
            ),
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(2026, 1, 4),
                payee="Publix",
                amount_cents=-5000,
                pending=False,
            ),
        ]
    )
    session.commit()

    pending = client.get("/api/transactions?pending=true").json()["items"]
    assert [t["payee"] for t in pending] == ["Shell"]
    assert all(t["pending"] for t in pending)
    assert client.get("/api/transactions/count?pending=true").json() == {"count": 1}


def test_transactions_count_and_uncategorized(
    client: TestClient, session: Session
) -> None:
    account, _group, category = seed_basics(session)
    session.add_all(
        [
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(2026, 1, 1),
                payee="Publix",
                amount_cents=-5000,
            ),
            Transaction(
                account_id=account.id,
                category_id=None,
                date=date(2026, 1, 2),
                payee="Payroll",
                amount_cents=300000,
            ),
        ]
    )
    session.commit()

    assert client.get("/api/transactions/count").json() == {"count": 2}
    assert client.get("/api/transactions/count?uncategorized=true").json() == {
        "count": 1
    }
    # Bad month on count is still 422, never 500.
    assert client.get("/api/transactions/count?month=2026-13").status_code == 422


def test_transactions_payees_suggestion(
    client: TestClient, session: Session
) -> None:
    account, group, category = seed_basics(session)
    other = Category(group_id=group.id, name="Dining", sort_order=1, archived=False)
    session.add(other)
    session.flush()
    # Publix appears mostly under Groceries -> suggested category should be it.
    for _ in range(3):
        session.add(
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(2026, 1, 1),
                payee="Publix",
                amount_cents=-5000,
            )
        )
    session.add(
        Transaction(
            account_id=account.id,
            category_id=other.id,
            date=date(2026, 1, 1),
            payee="Publix",
            amount_cents=-1000,
        )
    )
    session.commit()

    payees = client.get("/api/transactions/payees").json()
    assert len(payees) == 1
    assert payees[0]["payee"] == "Publix"
    assert payees[0]["suggested_category_id"] == category.id
    assert payees[0]["count"] == 4


# --- rules -----------------------------------------------------------------


def test_rules_crud_and_apply(client: TestClient, session: Session) -> None:
    account, _group, category = seed_basics(session)
    session.add(
        Transaction(
            account_id=account.id,
            category_id=None,
            date=date(2026, 1, 3),
            payee="PUBLIX #1234",
            amount_cents=-5000,
        )
    )
    session.commit()

    created = client.post(
        "/api/rules",
        json={
            "match_field": "payee",
            "pattern": "publix",
            "category_id": category.id,
            "priority": 10,
        },
    )
    assert created.status_code == 201

    assert len(client.get("/api/rules").json()) == 1

    # Apply to existing uncategorized transactions.
    applied = client.post("/api/rules/apply")
    assert applied.status_code == 200
    assert applied.json() == {"changed": 1}
    # Re-applying changes nothing (already categorized).
    assert client.post("/api/rules/apply").json() == {"changed": 0}


def test_create_rule_bad_category_is_404(client: TestClient) -> None:
    resp = client.post(
        "/api/rules",
        json={"match_field": "payee", "pattern": "x", "category_id": 9999},
    )
    assert resp.status_code == 404


# --- CSV import ------------------------------------------------------------

_SIMPLE_CSV = (
    "Date,Description,Amount\n"
    "01/15/2026,PUBLIX #1234,-52.30\n"
    "2026-01-16,\"ACME, INC PAYROLL\",2465.00\n"
    "\n"
    "Total,,-999.99\n"
)


def test_import_preview_and_commit(client: TestClient, session: Session) -> None:
    account, _group, _category = seed_basics(session)

    preview = client.post(
        "/api/import/preview",
        data={"account_id": str(account.id)},
        files={"file": ("bank.csv", _SIMPLE_CSV, "text/csv")},
    )
    assert preview.status_code == 200
    body = preview.json()
    token = body["token"]
    assert body["mapping"]["amount_shape"] == "signed"
    assert body["mapping"]["date_col"] == 0

    importable = [r for r in body["rows"] if r["importable"]]
    assert len(importable) == 2  # PUBLIX + ACME; the "Total" line is not importable
    assert any(not r["importable"] for r in body["rows"])  # summary line flagged

    commit = client.post(
        "/api/import/commit",
        json={
            "token": token,
            "rows": [
                {
                    "date": r["date"],
                    "payee": r["payee"],
                    "amount_cents": r["amount_cents"],
                    "memo": r["memo"],
                    "category_id": r["proposed_category_id"],
                    "is_duplicate": r["is_duplicate"],
                }
                for r in importable
            ],
            "skip_duplicates": True,
        },
    )
    assert commit.status_code == 200
    assert commit.json() == {"imported": 2, "skipped_duplicate": 0, "failed": 0}

    # Imported rows are tagged with source=csv (provenance), not manual.
    from app.models import TxnSource

    sources = {
        t.source
        for t in session.scalars(
            __import__("sqlalchemy").select(Transaction)
        )
    }
    assert sources == {TxnSource.csv}

    # A second preview now flags both rows as duplicates (hashes exist).
    preview2 = client.post(
        "/api/import/preview",
        data={"account_id": str(account.id)},
        files={"file": ("bank.csv", _SIMPLE_CSV, "text/csv")},
    )
    dup_rows = [r for r in preview2.json()["rows"] if r["importable"]]
    assert all(r["is_duplicate"] for r in dup_rows)

    # Committing again with skip_duplicates is idempotent: nothing new imported.
    commit2 = client.post(
        "/api/import/commit",
        json={
            "token": preview2.json()["token"],
            "rows": [
                {
                    "date": r["date"],
                    "payee": r["payee"],
                    "amount_cents": r["amount_cents"],
                    "memo": r["memo"],
                    "category_id": r["proposed_category_id"],
                    "is_duplicate": r["is_duplicate"],
                }
                for r in dup_rows
            ],
            "skip_duplicates": True,
        },
    )
    assert commit2.json()["imported"] == 0
    assert commit2.json()["skipped_duplicate"] == 2


def test_sync_claim_bad_token_is_400(client: TestClient) -> None:
    # Malformed setup token must be a clean 400, never a 500.
    resp = client.post("/api/sync/claim", json={"setup_token": "!!! not base64 !!!"})
    assert resp.status_code == 400
    assert "base64" in resp.json()["detail"].lower()


def test_import_preview_bad_account_is_404(client: TestClient) -> None:
    resp = client.post(
        "/api/import/preview",
        data={"account_id": "9999"},
        files={"file": ("bank.csv", _SIMPLE_CSV, "text/csv")},
    )
    assert resp.status_code == 404


# --- insights --------------------------------------------------------------


def _seed_for_insights(session: Session):
    account, group, category = seed_basics(session)
    other = Category(group_id=group.id, name="Dining", sort_order=1, archived=False)
    session.add(other)
    session.flush()
    # Two months of spending for the same categories, plus a monthly bill.
    for m, day in ((1, 5), (2, 5), (3, 5)):
        session.add(
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(2026, m, day),
                payee="Rocket Mortgage",
                amount_cents=-215000,
            )
        )
    session.add_all(
        [
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(2026, 3, 10),
                payee="Publix",
                amount_cents=-8000,
            ),
            Transaction(
                account_id=account.id,
                category_id=other.id,
                date=date(2026, 2, 12),
                payee="Restaurant",
                amount_cents=-5000,
            ),
            # Uncategorized income should be excluded from spend views.
            Transaction(
                account_id=account.id,
                category_id=None,
                date=date(2026, 3, 1),
                payee="Payroll",
                amount_cents=300000,
            ),
        ]
    )
    session.commit()
    return account, group, category, other


def test_insights_by_category(client: TestClient, session: Session) -> None:
    _seed_for_insights(session)
    resp = client.get("/api/insights/by-category?month=2026-03&compare_to=2026-02")
    assert resp.status_code == 200
    body = resp.json()
    assert body["month"] == "2026-03"
    assert body["compare_to"] == "2026-02"
    # March spend = 215000 + 8000 = 223000; income excluded.
    assert body["total_spent_cents"] == 223000
    assert body["groups"]  # non-empty
    # Bad month -> 422, never 500.
    assert client.get("/api/insights/by-category?month=2026-13").status_code == 422


def test_insights_trends(client: TestClient, session: Session) -> None:
    from app.insights import add_month, current_month

    account, _group, category = seed_basics(session)
    cur = current_month()
    for k in range(3):  # spend in each of the last three months
        m = add_month(cur, -k)
        year, month = int(m[:4]), int(m[5:7])
        session.add(
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(year, month, 5),
                payee="Netflix",
                amount_cents=-2000 * (k + 1),
            )
        )
    session.commit()

    resp = client.get("/api/insights/trends?months=6")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["months"]) == 6
    assert body["categories"]
    assert all("points" in c and len(c["points"]) == 6 for c in body["categories"])


def test_insights_trends_flags_outlier_with_reason(
    client: TestClient, session: Session
) -> None:
    from app.insights import add_month, current_month

    account, _group, category = seed_basics(session)
    cur = current_month()
    # Roughly ~$100 (with small variance) for five prior months, then a spike.
    prior = [-9000, -10000, -11000, -9500, -10500]
    for k in range(1, 6):
        m = add_month(cur, -k)
        y, mm = int(m[:4]), int(m[5:7])
        session.add(
            Transaction(
                account_id=account.id,
                category_id=category.id,
                date=date(y, mm, 10),
                payee="Steady",
                amount_cents=prior[k - 1],
            )
        )
    y, mm = int(cur[:4]), int(cur[5:7])
    session.add(
        Transaction(
            account_id=account.id,
            category_id=category.id,
            date=date(y, mm, 5),
            payee="Spike",
            amount_cents=-100000,
        )
    )
    session.commit()

    body = client.get("/api/insights/trends?months=6").json()
    flagged = next(c for c in body["categories"] if c["id"] == category.id)
    assert flagged["is_outlier"] is True
    assert flagged["reason"] and "above" in flagged["reason"]
    assert "σ" in flagged["reason"]


def test_insights_burn(client: TestClient, session: Session) -> None:
    _seed_for_insights(session)
    resp = client.get("/api/insights/burn?month=2026-03")
    assert resp.status_code == 200
    body = resp.json()
    assert body["days_in_month"] == 31
    assert body["current"]  # cumulative points
    assert len(body["history"]) == 3
    assert body["assumption"]


def test_insights_recurring(client: TestClient, session: Session) -> None:
    _seed_for_insights(session)
    resp = client.get("/api/insights/recurring")
    assert resp.status_code == 200
    body = resp.json()
    # Rocket Mortgage repeats monthly at a fixed amount -> detected.
    payees = [i["payee"] for i in body["items"]]
    assert "Rocket Mortgage" in payees
    mortgage = next(i for i in body["items"] if i["payee"] == "Rocket Mortgage")
    assert mortgage["average_amount_cents"] == -215000
    assert mortgage["occurrences"] == 3
    assert body["total_committed_monthly_cents"] >= 215000


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


def test_allocation_upsert_updates_existing(client: TestClient, session: Session) -> None:
    _account, _group, category = seed_basics(session)

    first = client.put(
        f"/api/budget/2026-01/allocations/{category.id}",
        json={"amount_cents": 25000},
    )
    assert first.status_code == 200
    assert first.json()["amount_cents"] == 25000

    # A second PUT for the same (month, category) must update, not 500 on the
    # UNIQUE constraint (atomic upsert / on-conflict path).
    second = client.put(
        f"/api/budget/2026-01/allocations/{category.id}",
        json={"amount_cents": 30000},
    )
    assert second.status_code == 200
    assert second.json()["amount_cents"] == 30000
    assert second.json()["id"] == first.json()["id"]


# --- goals -----------------------------------------------------------------


def test_goals_happy_path(client: TestClient, session: Session) -> None:
    _account, _group, category = seed_basics(session)
    session.add(
        Goal(
            category_id=category.id,
            kind=GoalKind.spending_cap,
            target_cents=80000,
            target_month=None,
        )
    )
    session.commit()

    resp = client.get("/api/goals")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["category_id"] == category.id
    assert body[0]["kind"] == "spending_cap"

    filtered = client.get(f"/api/goals?category_id={category.id}")
    assert len(filtered.json()) == 1
    assert client.get("/api/goals?category_id=9999").json() == []

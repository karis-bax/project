"""Tests for the pure budget engine (``app.budget``).

Each test gets a fresh in-memory SQLite database.
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import budget
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


def _current_month() -> str:
    return f"{date.today():%Y-%m}"


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db: Session) -> TestClient:
    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- helpers ---------------------------------------------------------------


def make_account(db: Session, name: str = "Checking") -> Account:
    acct = Account(
        name=name, kind=AccountKind.checking, opening_balance_cents=0, archived=False
    )
    db.add(acct)
    db.flush()
    return acct


def make_category(db: Session, name: str, *, group: CategoryGroup | None = None) -> Category:
    if group is None:
        group = CategoryGroup(name=f"{name} Group", sort_order=0)
        db.add(group)
        db.flush()
    cat = Category(group_id=group.id, name=name, sort_order=0, archived=False)
    db.add(cat)
    db.flush()
    return cat


def add_txn(
    db: Session,
    account: Account,
    when: date,
    amount_cents: int,
    *,
    category: Category | None = None,
    payee: str = "Test Payee",
    pending: bool = False,
) -> Transaction:
    txn = Transaction(
        account_id=account.id,
        category_id=category.id if category else None,
        date=when,
        payee=payee,
        amount_cents=amount_cents,
        memo="",
        cleared=not pending,
        pending=pending,
    )
    db.add(txn)
    db.flush()
    return txn


def allocate(db: Session, category: Category, month: str, amount_cents: int) -> Allocation:
    alloc = Allocation(month=month, category_id=category.id, amount_cents=amount_cents)
    db.add(alloc)
    db.flush()
    return alloc


def find_category_view(view: budget.MonthView, category_id: int) -> budget.CategoryView:
    for group in view.groups:
        for cat in group.categories:
            if cat.id == category_id:
                return cat
    raise AssertionError(f"category {category_id} not present in month view")


# --- 1. no allocation and no activity --------------------------------------


def test_category_with_no_allocation_and_no_activity(db: Session) -> None:
    make_account(db)
    cat = make_category(db, "Groceries")

    assert budget.assigned(db, cat, "2026-03") == 0
    assert budget.activity(db, cat, "2026-03") == 0
    assert budget.available(db, cat, "2026-03") == 0

    view = budget.month_view(db, "2026-03")
    cv = find_category_view(view, cat.id)
    assert (cv.assigned_cents, cv.activity_cents, cv.available_cents) == (0, 0, 0)


# --- 2. positive available carries across two months -----------------------


def test_positive_available_carries_forward(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Groceries")

    # Month 1: assign $200, spend $130 -> available 7000.
    allocate(db, cat, "2026-01", 20000)
    add_txn(db, acct, date(2026, 1, 10), -13000, category=cat)
    # Month 2: nothing happens.

    assert budget.available(db, cat, "2026-01") == 7000
    assert budget.available(db, cat, "2026-02") == 7000

    view2 = budget.month_view(db, "2026-02")
    cv = find_category_view(view2, cat.id)
    assert cv.assigned_cents == 0
    assert cv.activity_cents == 0
    assert cv.available_cents == 7000


# --- 3. NEGATIVE available carries across two months (overspend) -----------


def test_negative_available_carries_forward(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Dining")

    # Month 1: assign $50 but spend $120 -> overspent by $70 (-7000).
    allocate(db, cat, "2026-01", 5000)
    add_txn(db, acct, date(2026, 1, 15), -12000, category=cat)

    assert budget.available(db, cat, "2026-01") == -7000

    # Month 2: no new allocation or activity. Overspend must NOT reset to 0.
    assert budget.available(db, cat, "2026-02") == -7000

    view2 = budget.month_view(db, "2026-02")
    cv = find_category_view(view2, cat.id)
    assert cv.available_cents == -7000


# --- 4. left_to_assign when income exceeds assignments ---------------------


def test_left_to_assign_positive_when_income_exceeds_assignments(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Rent")

    # $3000 uncategorized income, only $1000 assigned.
    add_txn(db, acct, date(2026, 1, 1), 300000, category=None, payee="Payroll")
    allocate(db, cat, "2026-01", 100000)

    assert budget.income(db, "2026-01") == 300000
    assert budget.left_to_assign(db, "2026-01") == 200000

    view = budget.month_view(db, "2026-01")
    assert view.income_cents == 300000
    assert view.assigned_cents == 100000
    assert view.left_to_assign_cents == 200000


# --- 5. left_to_assign goes negative when assignments exceed income --------


def test_left_to_assign_negative_when_assignments_exceed_income(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Rent")

    add_txn(db, acct, date(2026, 1, 1), 50000, category=None, payee="Payroll")
    allocate(db, cat, "2026-01", 80000)

    assert budget.left_to_assign(db, "2026-01") == -30000

    view = budget.month_view(db, "2026-01")
    assert view.left_to_assign_cents == -30000


# --- 6. a month with no transactions at all --------------------------------


def test_month_with_no_transactions_at_all(db: Session) -> None:
    make_account(db)
    make_category(db, "Groceries")

    assert budget.income(db, "2026-05") == 0
    assert budget.left_to_assign(db, "2026-05") == 0

    view = budget.month_view(db, "2026-05")
    assert view.income_cents == 0
    assert view.assigned_cents == 0
    assert view.activity_cents == 0
    assert view.available_cents == 0
    assert view.left_to_assign_cents == 0
    # Groups/categories still render, all zeroed.
    all_cats = [c for g in view.groups for c in g.categories]
    assert all_cats and all(
        (c.assigned_cents, c.activity_cents, c.available_cents) == (0, 0, 0)
        for c in all_cats
    )


# --- 7. category created mid-history ---------------------------------------


def test_category_created_mid_history_has_no_prior_balance(db: Session) -> None:
    acct = make_account(db)

    # Establish history in Jan with an unrelated category.
    older = make_category(db, "Utilities")
    allocate(db, older, "2026-01", 10000)
    add_txn(db, acct, date(2026, 1, 5), -4000, category=older)

    # A new category only gets data starting in February.
    newbie = make_category(db, "Subscriptions")
    allocate(db, newbie, "2026-02", 3000)
    add_txn(db, acct, date(2026, 2, 20), -1000, category=newbie)

    # Before it existed (January), it has no balance.
    assert budget.available(db, newbie, "2026-01") == 0
    jan = find_category_view(budget.month_view(db, "2026-01"), newbie.id)
    assert (jan.assigned_cents, jan.activity_cents, jan.available_cents) == (0, 0, 0)

    # In February it reflects its own assignment and activity.
    assert budget.available(db, newbie, "2026-02") == 2000
    feb = find_category_view(budget.month_view(db, "2026-02"), newbie.id)
    assert feb.assigned_cents == 3000
    assert feb.activity_cents == -1000
    assert feb.available_cents == 2000


# --- pending transactions do not affect the budget ------------------------

_M = "2026-05"


def test_pending_transaction_does_not_affect_budget(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Groceries")
    add_txn(db, acct, date(2026, 5, 10), -5000, category=cat, pending=True)
    add_txn(db, acct, date(2026, 5, 1), 30000, category=None, pending=True)

    assert budget.activity(db, cat, _M) == 0
    assert budget.available(db, cat, _M) == 0
    assert budget.income(db, _M) == 0
    assert budget.left_to_assign(db, _M) == 0

    view = budget.month_view(db, _M)
    assert view.activity_cents == 0
    assert view.available_cents == 0
    assert view.left_to_assign_cents == 0


def test_posting_moves_budget_by_the_posted_amount(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Groceries")
    # A categorized expense moves activity/available; uncategorized income moves
    # left_to_assign. (In this envelope model a single txn can't move all three.)
    add_txn(db, acct, date(2026, 5, 10), -5000, category=cat, pending=False)
    add_txn(db, acct, date(2026, 5, 1), 30000, category=None, pending=False)

    assert budget.activity(db, cat, _M) == -5000
    assert budget.available(db, cat, _M) == -5000
    assert budget.income(db, _M) == 30000
    assert budget.left_to_assign(db, _M) == 30000


def test_pending_figure_equals_sum_of_pending_rows(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Dining")
    add_txn(db, acct, date(2026, 5, 3), -4300, category=cat, pending=True)
    add_txn(db, acct, date(2026, 5, 8), -1200, category=cat, pending=True)
    add_txn(db, acct, date(2026, 5, 9), -900, category=cat, pending=False)  # settled

    view = budget.month_view(db, _M)
    row = find_category_view(view, cat.id)
    assert row.pending_cents == -5500  # sum of the two pending rows only
    assert row.activity_cents == -900  # settled money only
    assert view.pending_cents == -5500


def test_month_with_only_pending_has_zero_activity(db: Session) -> None:
    acct = make_account(db)
    cat = make_category(db, "Fun")
    add_txn(db, acct, date(2026, 5, 4), -2500, category=cat, pending=True)

    assert budget.activity(db, cat, _M) == 0
    assert budget.month_view(db, _M).activity_cents == 0


def test_settled_transactions_still_count(db: Session) -> None:
    # Regression guard: the exclusion targets ONLY pending rows.
    acct = make_account(db)
    cat = make_category(db, "Bills")
    add_txn(db, acct, date(2026, 5, 6), -5000, category=cat, pending=False)
    add_txn(db, acct, date(2026, 5, 7), -3000, category=cat, pending=True)

    assert budget.activity(db, cat, _M) == -5000  # pending -3000 excluded
    row = find_category_view(budget.month_view(db, _M), cat.id)
    assert row.activity_cents == -5000
    assert row.pending_cents == -3000


# --- archiving a category (the zombie-category bug) ------------------------


def _category_ids_in_view(view: dict) -> list[int]:
    return [c["id"] for g in view["groups"] for c in g["categories"]]


def test_archiving_category_returns_money_and_hides_it(
    client: TestClient, db: Session
) -> None:
    make_account(db)
    cat = make_category(db, "Subscriptions")
    month = _current_month()

    pre = client.get(f"/api/budget/{month}").json()["left_to_assign_cents"]

    assigned = client.put(
        f"/api/budget/{month}/allocations/{cat.id}", json={"amount_cents": 10000}
    )
    assert assigned.status_code == 200
    after_alloc = client.get(f"/api/budget/{month}").json()
    assert after_alloc["left_to_assign_cents"] == pre - 10000

    deleted = client.delete(f"/api/categories/{cat.id}")
    assert deleted.status_code == 200

    view = client.get(f"/api/budget/{month}").json()
    # The archived category must be gone from the current month …
    assert cat.id not in _category_ids_in_view(view)
    # … and its allocation returned to left-to-assign.
    assert view["left_to_assign_cents"] == pre


def test_archiving_preserves_past_month_totals(
    client: TestClient, db: Session
) -> None:
    acct = make_account(db)
    cat = make_category(db, "Dining")
    # A fully-spent past month (allocation == spending -> zero carryover).
    allocate(db, cat, "2026-01", 5000)
    add_txn(db, acct, date(2026, 1, 15), -5000, category=cat)
    db.commit()

    before = client.get("/api/budget/2026-01").json()
    deleted = client.delete(f"/api/categories/{cat.id}")
    assert deleted.status_code == 200  # no residual, so no absorb/discard needed
    after = client.get("/api/budget/2026-01").json()

    # The archived category still had real activity in January, so that month's
    # totals and rows must be byte-for-byte identical.
    assert after == before
    assert cat.id in _category_ids_in_view(after)


def test_archiving_nonzero_available_requires_absorb_or_discard(
    client: TestClient, db: Session
) -> None:
    make_account(db)
    cat = make_category(db, "Vacation")
    # $340 assigned in a past month, never spent -> carries into now.
    allocate(db, cat, "2026-01", 34000)
    db.commit()

    conflict = client.delete(f"/api/categories/{cat.id}")
    assert conflict.status_code == 409
    assert "340.00" in conflict.json()["detail"]

    # Nothing changed: the category is not archived and the allocation remains.
    assert budget.available(db, cat, _current_month()) == 34000


def test_archiving_with_discard_writes_off_balance(
    client: TestClient, db: Session
) -> None:
    make_account(db)
    cat = make_category(db, "Vacation")
    allocate(db, cat, "2026-01", 34000)
    db.commit()

    deleted = client.delete(f"/api/categories/{cat.id}?discard=true")
    assert deleted.status_code == 200
    assert deleted.json()["archived"] is True
    view = client.get(f"/api/budget/{_current_month()}").json()
    assert cat.id not in _category_ids_in_view(view)


def test_archiving_with_absorb_moves_balance_to_target(
    client: TestClient, db: Session
) -> None:
    make_account(db)
    source = make_category(db, "Vacation")
    target = make_category(db, "Emergency")
    allocate(db, source, "2026-01", 34000)
    db.commit()

    month = _current_month()
    deleted = client.delete(
        f"/api/categories/{source.id}?absorb_to={target.id}"
    )
    assert deleted.status_code == 200

    view = client.get(f"/api/budget/{month}").json()
    assert source.id not in _category_ids_in_view(view)
    target_row = next(
        c
        for g in view["groups"]
        for c in g["categories"]
        if c["id"] == target.id
    )
    # The residual moved into the target's envelope.
    assert target_row["available_cents"] == 34000

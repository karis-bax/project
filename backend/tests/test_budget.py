"""Tests for the pure budget engine (``app.budget``).

Each test gets a fresh in-memory SQLite database.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app import budget
from app.db import Base
from app.models import (
    Account,
    AccountKind,
    Allocation,
    Category,
    CategoryGroup,
    Transaction,
)


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
) -> Transaction:
    txn = Transaction(
        account_id=account.id,
        category_id=category.id if category else None,
        date=when,
        payee=payee,
        amount_cents=amount_cents,
        memo="",
        cleared=True,
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

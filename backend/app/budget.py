"""Envelope budget engine — a pure computation module.

This file must never import FastAPI (or anything HTTP). It takes a SQLAlchemy
``Session`` and returns plain dataclasses so it can be unit-tested in isolation.

Definitions (all amounts are signed integer cents):

- ``activity(category, month)``   = sum of ``amount_cents`` for that category's
  transactions dated inside ``month``. Negative for spending.
- ``assigned(category, month)``   = the ``Allocation`` amount for
  ``(month, category)``, or 0 when there is no allocation.
- ``available(category, month)``  = ``available(category, previous month)``
  ``+ assigned + activity``, with the recursion floored at the earliest month
  that has any data.

  IMPORTANT PRODUCT DECISION — DO NOT "FIX" THIS:
  A negative ``available`` carries forward as a negative number. Overspending is
  **not** reset to zero at the month boundary; the overspent amount rolls into
  the next month so the household actually has to make it up. Resetting to zero
  would silently hide overspending and is explicitly wrong for this app.

- ``income(month)``               = sum of the POSITIVE ``amount_cents`` for
  transactions whose ``category_id IS NULL`` in ``month`` (uncategorized inflow).
- ``left_to_assign(month)``       = ``income(month)`` + the unassigned carryover
  from the previous month − the total assigned in ``month``.

Performance: ``month_view`` computes an entire month in a small, fixed number of
aggregate queries (independent of the number of categories or months). It loads
all allocations, all monthly categorized-activity sums, and all monthly income
once, then folds forward in Python. It never issues one query per category and
never walks backward one month at a time.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Allocation, Category, CategoryGroup, Transaction

_MONTH_FMT = "%Y-%m"


# --- Return types ----------------------------------------------------------


@dataclass(frozen=True)
class CategoryView:
    id: int
    name: str
    assigned_cents: int
    activity_cents: int
    available_cents: int


@dataclass(frozen=True)
class GroupView:
    id: int
    name: str
    categories: list[CategoryView]
    assigned_cents: int
    activity_cents: int
    available_cents: int


@dataclass(frozen=True)
class MonthView:
    month: str
    groups: list[GroupView]
    income_cents: int
    assigned_cents: int
    activity_cents: int
    available_cents: int
    left_to_assign_cents: int


# --- Month string helpers --------------------------------------------------


def _txn_month():
    """SQL expression for a transaction's ``YYYY-MM`` budget month."""

    return func.strftime(_MONTH_FMT, Transaction.date)


def _prev_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    mon -= 1
    if mon == 0:
        year, mon = year - 1, 12
    return f"{year:04d}-{mon:02d}"


def _next_month(month: str) -> str:
    year, mon = int(month[:4]), int(month[5:7])
    mon += 1
    if mon == 13:
        year, mon = year + 1, 1
    return f"{year:04d}-{mon:02d}"


def previous_month(month: str) -> str:
    """Public helper: the ``YYYY-MM`` month before ``month``."""

    return _prev_month(month)


def _month_range(start: str, end: str) -> list[str]:
    """Contiguous ``YYYY-MM`` months from ``start`` to ``end`` inclusive."""

    if start > end:
        return [end]
    months: list[str] = []
    cur = start
    while cur <= end:
        months.append(cur)
        cur = _next_month(cur)
    return months


# --- Bulk loaders (each is a single aggregate query) -----------------------


def _earliest_month(db: Session) -> str | None:
    """The earliest month with any data, across transactions and allocations."""

    txn_min = db.scalar(select(func.min(_txn_month())))
    alloc_min = db.scalar(select(func.min(Allocation.month)))
    present = [m for m in (txn_min, alloc_min) if m is not None]
    return min(present) if present else None


def _activity_by_month_category(db: Session, upto: str) -> dict[tuple[str, int], int]:
    month = _txn_month()
    rows = db.execute(
        select(month, Transaction.category_id, func.sum(Transaction.amount_cents))
        .where(Transaction.category_id.is_not(None))
        .where(month <= upto)
        .group_by(month, Transaction.category_id)
    ).all()
    return {(row[0], row[1]): int(row[2]) for row in rows}


def _assigned_by_month_category(db: Session, upto: str) -> dict[tuple[str, int], int]:
    rows = db.execute(
        select(Allocation.month, Allocation.category_id, func.sum(Allocation.amount_cents))
        .where(Allocation.month <= upto)
        .group_by(Allocation.month, Allocation.category_id)
    ).all()
    return {(row[0], row[1]): int(row[2]) for row in rows}


def _income_by_month(db: Session, upto: str) -> dict[str, int]:
    month = _txn_month()
    rows = db.execute(
        select(month, func.sum(Transaction.amount_cents))
        .where(Transaction.category_id.is_(None))
        .where(Transaction.amount_cents > 0)
        .where(month <= upto)
        .group_by(month)
    ).all()
    return {row[0]: int(row[1]) for row in rows}


# --- Named definitions (thin, forward-folding wrappers) --------------------


def activity(db: Session, category: Category, month: str) -> int:
    """Sum of ``amount_cents`` for ``category`` dated inside ``month``."""

    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.category_id == category.id)
        .where(_txn_month() == month)
    )
    return int(total or 0)


def assigned(db: Session, category: Category, month: str) -> int:
    """The allocated amount for ``(month, category)``, or 0."""

    total = db.scalar(
        select(func.coalesce(func.sum(Allocation.amount_cents), 0))
        .where(Allocation.category_id == category.id)
        .where(Allocation.month == month)
    )
    return int(total or 0)


def income(db: Session, month: str) -> int:
    """Sum of positive uncategorized inflow in ``month``."""

    total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .where(Transaction.category_id.is_(None))
        .where(Transaction.amount_cents > 0)
        .where(_txn_month() == month)
    )
    return int(total or 0)


def available(db: Session, category: Category, month: str) -> int:
    """Running available for ``category`` at the end of ``month``.

    Folds forward from the earliest month with data; negative balances carry
    (see the module docstring — overspending is intentionally not reset).
    """

    floor = _earliest_month(db)
    start = month if (floor is None or floor > month) else floor
    act = _activity_by_month_category(db, month)
    asg = _assigned_by_month_category(db, month)
    total = 0
    for m in _month_range(start, month):
        total += asg.get((m, category.id), 0) + act.get((m, category.id), 0)
    return total


def left_to_assign(db: Session, month: str) -> int:
    """Unassigned money available to budget as of ``month``.

    Equals the running sum of ``income - total_assigned`` from the earliest
    month with data through ``month``.
    """

    floor = _earliest_month(db)
    start = month if (floor is None or floor > month) else floor
    inc = _income_by_month(db, month)
    asg = _assigned_by_month_category(db, month)
    assigned_totals: dict[str, int] = {}
    for (m, _cat_id), amount in asg.items():
        assigned_totals[m] = assigned_totals.get(m, 0) + amount
    return sum(
        inc.get(m, 0) - assigned_totals.get(m, 0) for m in _month_range(start, month)
    )


# --- The main entry point --------------------------------------------------


def month_view(db: Session, month: str) -> MonthView:
    """Compute the full budget view for ``month`` in a fixed set of queries."""

    groups = list(
        db.scalars(
            select(CategoryGroup).order_by(CategoryGroup.sort_order, CategoryGroup.id)
        )
    )
    categories = list(
        db.scalars(
            select(Category).order_by(
                Category.group_id, Category.sort_order, Category.id
            )
        )
    )

    floor = _earliest_month(db)
    start = month if (floor is None or floor > month) else floor
    months = _month_range(start, month)

    activity_map = _activity_by_month_category(db, month)
    assigned_map = _assigned_by_month_category(db, month)
    income_map = _income_by_month(db, month)

    assigned_totals: dict[str, int] = {}
    for (m, _cat_id), amount in assigned_map.items():
        assigned_totals[m] = assigned_totals.get(m, 0) + amount

    # Fold available forward once per category (Python, not SQL).
    available_by_cat: dict[int, int] = {}
    for cat in categories:
        running = 0
        for m in months:
            running += assigned_map.get((m, cat.id), 0) + activity_map.get(
                (m, cat.id), 0
            )
        available_by_cat[cat.id] = running

    cats_by_group: dict[int, list[Category]] = {}
    for cat in categories:
        cats_by_group.setdefault(cat.group_id, []).append(cat)

    group_views: list[GroupView] = []
    total_assigned = total_activity = total_available = 0
    for group in groups:
        cat_views: list[CategoryView] = []
        g_assigned = g_activity = g_available = 0
        for cat in cats_by_group.get(group.id, []):
            c_assigned = assigned_map.get((month, cat.id), 0)
            c_activity = activity_map.get((month, cat.id), 0)
            c_available = available_by_cat[cat.id]
            cat_views.append(
                CategoryView(
                    id=cat.id,
                    name=cat.name,
                    assigned_cents=c_assigned,
                    activity_cents=c_activity,
                    available_cents=c_available,
                )
            )
            g_assigned += c_assigned
            g_activity += c_activity
            g_available += c_available
        group_views.append(
            GroupView(
                id=group.id,
                name=group.name,
                categories=cat_views,
                assigned_cents=g_assigned,
                activity_cents=g_activity,
                available_cents=g_available,
            )
        )
        total_assigned += g_assigned
        total_activity += g_activity
        total_available += g_available

    month_income = income_map.get(month, 0)
    lta = sum(
        income_map.get(m, 0) - assigned_totals.get(m, 0) for m in months
    )

    return MonthView(
        month=month,
        groups=group_views,
        income_cents=month_income,
        assigned_cents=total_assigned,
        activity_cents=total_activity,
        available_cents=total_available,
        left_to_assign_cents=lta,
    )

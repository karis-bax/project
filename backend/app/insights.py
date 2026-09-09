"""Insights aggregates — all computed on the server (never in the browser).

Spending is reported as a positive magnitude of outflows (negative
``amount_cents``); income and transfers-in are excluded from spend views.
"""

from __future__ import annotations

import calendar
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import schemas
from .importer import normalize_payee
from .models import Category, CategoryGroup, Transaction

_MONTH = "%Y-%m"


def add_month(month: str, delta: int) -> str:
    year = int(month[:4])
    index = int(month[5:7]) - 1 + delta
    year += index // 12
    index %= 12
    return f"{year:04d}-{index + 1:02d}"


def current_month(today: date | None = None) -> str:
    today = today or date.today()
    return f"{today.year:04d}-{today.month:02d}"


# --- 1. by category --------------------------------------------------------


def _spend_by_category(db: Session, month: str) -> dict[int, int]:
    """category_id -> positive spend magnitude for the month."""

    rows = db.execute(
        select(Transaction.category_id, func.sum(Transaction.amount_cents))
        .where(Transaction.category_id.is_not(None))
        .where(Transaction.amount_cents < 0)
        .where(func.strftime(_MONTH, Transaction.date) == month)
        .group_by(Transaction.category_id)
    ).all()
    return {cid: -int(total) for cid, total in rows}


def by_category(
    db: Session, month: str, compare_to: str | None
) -> schemas.ByCategoryResponse:
    compare_to = compare_to or add_month(month, -1)
    this = _spend_by_category(db, month)
    prev = _spend_by_category(db, compare_to)

    groups = db.scalars(
        select(CategoryGroup).order_by(CategoryGroup.sort_order, CategoryGroup.id)
    ).all()
    categories = db.scalars(select(Category)).all()
    cats_by_group: dict[int, list[Category]] = defaultdict(list)
    for c in categories:
        cats_by_group[c.group_id].append(c)

    group_out: list[schemas.GroupSpend] = []
    total_spent = total_compare = 0
    for g in groups:
        cat_out: list[schemas.CategorySpend] = []
        g_spent = g_compare = 0
        for c in sorted(cats_by_group.get(g.id, []), key=lambda x: x.sort_order):
            s = this.get(c.id, 0)
            p = prev.get(c.id, 0)
            if s == 0 and p == 0:
                continue
            cat_out.append(
                schemas.CategorySpend(
                    id=c.id, name=c.name, spent_cents=s, compare_cents=p
                )
            )
            g_spent += s
            g_compare += p
        if g_spent == 0 and g_compare == 0:
            continue
        cat_out.sort(key=lambda x: x.spent_cents, reverse=True)
        group_out.append(
            schemas.GroupSpend(
                id=g.id,
                name=g.name,
                spent_cents=g_spent,
                compare_cents=g_compare,
                categories=cat_out,
            )
        )
        total_spent += g_spent
        total_compare += g_compare

    group_out.sort(key=lambda x: x.spent_cents, reverse=True)
    return schemas.ByCategoryResponse(
        month=month,
        compare_to=compare_to,
        total_spent_cents=total_spent,
        total_compare_cents=total_compare,
        groups=group_out,
    )


# --- 2. trends -------------------------------------------------------------


def trends(db: Session, months: int, anchor: str | None = None) -> schemas.TrendsResponse:
    anchor = anchor or current_month()
    month_list = [add_month(anchor, -(months - 1 - i)) for i in range(months)]
    month_set = set(month_list)

    rows = db.execute(
        select(
            Transaction.category_id,
            func.strftime(_MONTH, Transaction.date),
            func.sum(Transaction.amount_cents),
        )
        .where(Transaction.category_id.is_not(None))
        .where(Transaction.amount_cents < 0)
        .group_by(Transaction.category_id, func.strftime(_MONTH, Transaction.date))
    ).all()

    per_cat: dict[int, dict[str, int]] = defaultdict(dict)
    for cid, m, total in rows:
        if m in month_set:
            per_cat[cid][m] = -int(total)

    categories = {c.id: c for c in db.scalars(select(Category))}

    out: list[schemas.TrendCategory] = []
    for cid, by_month in per_cat.items():
        cat = categories.get(cid)
        if cat is None:
            continue
        points = [
            schemas.TrendPoint(month=m, spent_cents=by_month.get(m, 0))
            for m in month_list
        ]
        trailing = [p.spent_cents for p in points[:-1]]
        current = points[-1].spent_cents
        mean = statistics.mean(trailing) if trailing else 0
        stddev = statistics.pstdev(trailing) if len(trailing) >= 2 else 0.0

        is_outlier = False
        reason: str | None = None
        direction = "above" if current > mean else "below"
        if stddev > 0 and abs(current - mean) > 1.5 * stddev:
            is_outlier = True
            sigma = abs(current - mean) / stddev
            reason = (
                f"This month's ${current / 100:,.0f} is {sigma:.1f}σ {direction} "
                f"your {len(trailing)}-month average of ${mean / 100:,.0f}."
            )
        elif stddev == 0 and len(trailing) >= 2 and current != mean:
            # A perfectly flat history: any change is a break from the pattern.
            is_outlier = True
            reason = (
                f"This month's ${current / 100:,.0f} is {direction} a previously "
                f"flat ${mean / 100:,.0f} every month."
            )

        out.append(
            schemas.TrendCategory(
                id=cid,
                name=cat.name,
                points=points,
                current_month=anchor,
                mean_cents=round(mean),
                stddev_cents=round(stddev),
                is_outlier=is_outlier,
                reason=reason,
            )
        )

    # Outliers first, then by spend.
    out.sort(key=lambda c: (not c.is_outlier, -c.points[-1].spent_cents))
    return schemas.TrendsResponse(months=month_list, categories=out)


# --- 3. burn ---------------------------------------------------------------


def _daily_cumulative(db: Session, month: str, max_day: int) -> list[schemas.BurnPoint]:
    rows = db.execute(
        select(
            func.strftime("%d", Transaction.date),
            func.sum(Transaction.amount_cents),
        )
        .where(Transaction.amount_cents < 0)
        .where(func.strftime(_MONTH, Transaction.date) == month)
        .group_by(func.strftime("%d", Transaction.date))
    ).all()
    per_day = {int(day): -int(total) for day, total in rows}
    points: list[schemas.BurnPoint] = []
    running = 0
    for day in range(1, max_day + 1):
        running += per_day.get(day, 0)
        points.append(schemas.BurnPoint(day=day, cumulative_cents=running))
    return points


def burn(db: Session, month: str, today: date | None = None) -> schemas.BurnResponse:
    today = today or date.today()
    year, mon = int(month[:4]), int(month[5:7])
    days_in_month = calendar.monthrange(year, mon)[1]

    is_current = current_month(today) == month
    as_of_day = today.day if is_current else days_in_month
    as_of_day = min(as_of_day, days_in_month)

    current = _daily_cumulative(db, month, as_of_day)
    history = [
        schemas.BurnSeries(
            month=add_month(month, -k),
            points=_daily_cumulative(db, add_month(month, -k), days_in_month),
        )
        for k in (1, 2, 3)
    ]

    projected_total: int | None = None
    if as_of_day > 0 and current:
        spent_so_far = current[-1].cumulative_cents
        projected_total = round(spent_so_far / as_of_day * days_in_month)

    assumption = (
        f"Projection assumes the rest of the month continues at the average "
        f"daily spend over the first {as_of_day} day(s)."
    )
    return schemas.BurnResponse(
        month=month,
        days_in_month=days_in_month,
        as_of_day=as_of_day,
        current=current,
        history=history,
        projected_total_cents=projected_total,
        assumption=assumption,
    )


# --- 4. recurring ----------------------------------------------------------


def recurring(db: Session) -> schemas.RecurringResponse:
    rows = db.execute(
        select(
            Transaction.payee,
            Transaction.date,
            Transaction.amount_cents,
            Transaction.category_id,
        )
        .where(Transaction.amount_cents < 0)
        .order_by(Transaction.date)
    ).all()

    groups: dict[str, list[tuple[date, int, str, int | None]]] = defaultdict(list)
    for payee, d, amount, category_id in rows:
        groups[normalize_payee(payee)].append((d, amount, payee, category_id))

    categories = {c.id: c.name for c in db.scalars(select(Category))}
    items: list[schemas.RecurringItem] = []

    for occurrences in groups.values():
        if len(occurrences) < 3:
            continue
        occurrences.sort(key=lambda o: o[0])
        dates = [o[0] for o in occurrences]
        amounts = [o[1] for o in occurrences]
        gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        monthly_gaps = [g for g in gaps if 25 <= g <= 35]
        if len(monthly_gaps) < max(1, len(gaps) // 2):
            continue  # not predominantly monthly

        median_amount = statistics.median(amounts)
        if median_amount == 0:
            continue
        within_10 = all(
            abs(abs(a) - abs(median_amount)) * 10 <= abs(median_amount) for a in amounts
        )
        if not within_10:
            continue

        avg = round(statistics.mean(amounts))
        cadence = round(statistics.median(monthly_gaps)) or 30
        last_date = dates[-1]
        next_date = last_date + timedelta(days=cadence)
        display_payee = Counter(o[2] for o in occurrences).most_common(1)[0][0]
        cat_votes = Counter(o[3] for o in occurrences if o[3] is not None)
        category_id = cat_votes.most_common(1)[0][0] if cat_votes else None

        items.append(
            schemas.RecurringItem(
                payee=display_payee,
                category_id=category_id,
                category_name=categories.get(category_id) if category_id else None,
                average_amount_cents=avg,
                cadence_days=cadence,
                occurrences=len(occurrences),
                last_date=last_date.isoformat(),
                next_expected_date=next_date.isoformat(),
                next_expected_amount_cents=avg,
            )
        )

    items.sort(key=lambda i: i.average_amount_cents)  # largest spend (most negative) first
    total = sum(abs(i.average_amount_cents) for i in items)
    return schemas.RecurringResponse(items=items, total_committed_monthly_cents=total)

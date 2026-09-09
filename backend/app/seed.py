"""Idempotent demo-data loader for Envelope.

Builds one realistic Southwest Florida household: three accounts, six category
groups with several categories each, and roughly 180 transactions across the
last four months (recurring bills, groceries/gas, irregular one-offs, and two
paychecks a month as uncategorized income).

The generator is deterministic (fixed RNG seed), and every transaction carries a
stable ``import_hash``. Reference data is created via get-or-create. Running the
seed twice therefore never duplicates anything.
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import unscoped_session, user_session
from .models import (
    Account,
    AccountKind,
    Allocation,
    Category,
    CategoryGroup,
    CategoryRule,
    Goal,
    GoalKind,
    Transaction,
)

RNG_SEED = 20260501

# Category groups (in display order) and their categories.
GROUPS: dict[str, list[str]] = {
    "Housing": ["Mortgage", "Home Maintenance", "HOA Fees", "Furnishings"],
    "Food": ["Groceries", "Restaurants", "Coffee Shops", "Fast Food", "Alcohol"],
    "Transportation": [
        "Gas",
        "Car Payment",
        "Auto Insurance",
        "Car Maintenance",
        "Parking & Tolls",
    ],
    "Bills": ["Electric", "Water & Sewer", "Internet & Phone", "Streaming", "Trash"],
    "Fun": ["Entertainment", "Hobbies", "Vacation", "Gym", "Shopping"],
    "Savings": ["Emergency Fund", "Vacation Fund", "New Car Fund", "Retirement"],
}

ACCOUNTS: list[tuple[str, AccountKind, int]] = [
    ("Everyday Checking", AccountKind.checking, 4_20_000),
    ("Emergency Savings", AccountKind.savings, 8_50_000),
    ("Rewards Credit Card", AccountKind.credit, -1_25_000),
]


def _dollars(amount: int) -> int:
    """Whole dollars to signed integer cents."""

    return amount * 100


def _hash(*parts: object) -> str:
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_or_create(
    db: Session,
    model: type,
    defaults: dict | None = None,
    **filters: object,
):
    """Return an existing row matching ``filters`` or create one."""

    obj = db.scalars(select(model).filter_by(**filters)).first()
    if obj is not None:
        return obj, False
    obj = model(**{**filters, **(defaults or {})})
    db.add(obj)
    db.flush()
    return obj, True


def _month_starts(n: int = 4) -> list[date]:
    """First day of each of the last ``n`` months, oldest first."""

    today = date.today()
    year, month = today.year, today.month
    starts: list[date] = []
    for _ in range(n):
        starts.append(date(year, month, 1))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    starts.reverse()
    return starts


def _day(base: date, day: int, today: date) -> date | None:
    """A date in ``base``'s month on ``day``; None if it lands in the future."""

    try:
        d = base.replace(day=day)
    except ValueError:
        return None
    if d > today:
        return None
    return d


def _ensure_reference_data(
    db: Session,
) -> tuple[dict[str, Account], dict[str, Category]]:
    accounts: dict[str, Account] = {}
    for name, kind, opening in ACCOUNTS:
        acct, _ = get_or_create(
            db,
            Account,
            defaults={"kind": kind, "opening_balance_cents": opening},
            name=name,
        )
        accounts[kind.value] = acct

    categories: dict[str, Category] = {}
    for g_order, (group_name, cat_names) in enumerate(GROUPS.items()):
        group, _ = get_or_create(
            db, CategoryGroup, defaults={"sort_order": g_order}, name=group_name
        )
        for c_order, cat_name in enumerate(cat_names):
            cat, _ = get_or_create(
                db,
                Category,
                defaults={"sort_order": c_order},
                group_id=group.id,
                name=cat_name,
            )
            categories[f"{group_name}/{cat_name}"] = cat
    return accounts, categories


# Irregular one-off pools: (payee, "Group/Category", account_kind, min$, max$).
_ONE_OFFS: list[tuple[str, str, str, int, int]] = [
    ("First Watch", "Food/Restaurants", "credit", 24, 68),
    ("Ford's Garage Fort Myers", "Food/Restaurants", "credit", 38, 96),
    ("Texas Roadhouse", "Food/Restaurants", "credit", 42, 110),
    ("Blue Pointe Oyster Bar", "Food/Restaurants", "credit", 55, 140),
    ("Chick-fil-A", "Food/Fast Food", "credit", 9, 26),
    ("Culver's", "Food/Fast Food", "credit", 11, 29),
    ("PDQ Cape Coral", "Food/Fast Food", "credit", 12, 31),
    ("Publix Liquors", "Food/Alcohol", "credit", 18, 62),
    ("Total Wine & More", "Food/Alcohol", "credit", 24, 85),
    ("The Home Depot", "Housing/Home Maintenance", "credit", 22, 240),
    ("Lowe's Home Improvement", "Housing/Home Maintenance", "credit", 18, 180),
    ("Rooms To Go", "Housing/Furnishings", "credit", 120, 640),
    ("AMC Merchants Crossing", "Fun/Entertainment", "credit", 18, 64),
    ("Regal Belltower", "Fun/Entertainment", "credit", 20, 58),
    ("Topgolf Fort Myers", "Fun/Entertainment", "credit", 35, 120),
    ("Amazon", "Fun/Shopping", "credit", 12, 160),
    ("Target Cape Coral", "Fun/Shopping", "credit", 24, 145),
    ("Miromar Outlets", "Fun/Shopping", "credit", 35, 210),
    ("Bass Pro Shops", "Fun/Hobbies", "credit", 25, 180),
    ("Michaels", "Fun/Hobbies", "credit", 12, 70),
    ("Tuffy Auto Service", "Transportation/Car Maintenance", "credit", 45, 380),
    ("SunPass Toll", "Transportation/Parking & Tolls", "checking", 15, 40),
    ("Southwest Airlines", "Fun/Vacation", "credit", 180, 520),
]


def _build_transactions(
    accounts: dict[str, Account], categories: dict[str, Category]
) -> list[dict]:
    rng = random.Random(RNG_SEED)
    today = date.today()
    txns: list[dict] = []

    checking = accounts["checking"]
    savings = accounts["savings"]
    credit = accounts["credit"]

    def add(
        account: Account,
        cat_key: str | None,
        when: date | None,
        payee: str,
        amount_cents: int,
        memo: str = "",
    ) -> None:
        if when is None:
            return
        category = categories[cat_key] if cat_key else None
        txns.append(
            {
                "account": account,
                "category": category,
                "date": when,
                "payee": payee,
                "amount_cents": amount_cents,
                "memo": memo,
                "cleared": when <= today - timedelta(days=4),
            }
        )

    for base in _month_starts(4):
        # Two paychecks a month: uncategorized income (positive, category=None).
        add(checking, None, _day(base, 1, today), "Gulf Coast Health — Payroll", _dollars(2_465))
        add(checking, None, _day(base, 15, today), "Gulf Coast Health — Payroll", _dollars(2_465))

        # Fixed monthly bills (outflows -> negative).
        add(checking, "Housing/Mortgage", _day(base, 1, today), "Rocket Mortgage", -_dollars(2_150))
        add(checking, "Housing/HOA Fees", _day(base, 5, today), "Cape Coral HOA", -_dollars(285))
        add(checking, "Transportation/Car Payment", _day(base, 7, today), "Toyota Financial Svc", -_dollars(429))
        add(checking, "Transportation/Auto Insurance", _day(base, 12, today), "State Farm Insurance", -_dollars(168))
        add(checking, "Bills/Electric", _day(base, 15, today), "Duke Energy", -_dollars(rng.randint(142, 268)))
        add(checking, "Bills/Water & Sewer", _day(base, 18, today), "City of Cape Coral Utilities", -_dollars(rng.randint(64, 108)))
        add(checking, "Bills/Internet & Phone", _day(base, 20, today), "Verizon", -_dollars(180))
        add(checking, "Bills/Trash", _day(base, 20, today), "Waste Pro", -_dollars(34))
        add(checking, "Bills/Streaming", _day(base, 9, today), "Netflix", -_dollars(23))
        add(checking, "Bills/Streaming", _day(base, 9, today), "Disney+", -_dollars(14))
        add(checking, "Fun/Gym", _day(base, 3, today), "LA Fitness", -_dollars(45))

        # Monthly transfers into savings envelopes (inflow to the savings acct).
        add(savings, "Savings/Emergency Fund", _day(base, 2, today), "Transfer to Savings", _dollars(400), "Monthly transfer")
        add(savings, "Savings/Retirement", _day(base, 2, today), "Transfer to Savings", _dollars(300), "Monthly transfer")
        add(savings, "Savings/Vacation Fund", _day(base, 16, today), "Transfer to Savings", _dollars(150), "Monthly transfer")

        # Weekly-ish groceries (Publix) on the credit card.
        for day in (3, 9, 16, 22, 27, 30):
            add(credit, "Food/Groceries", _day(base, day, today), "Publix", -_dollars(rng.randint(52, 176)))

        # Fuel (Chevron) on the credit card.
        for day in (5, 13, 21, 28):
            add(credit, "Transportation/Gas", _day(base, day, today), "Chevron", -_dollars(rng.randint(38, 74)))

        # Coffee / convenience (Wawa).
        for day in (6, 19, 25):
            add(credit, "Food/Coffee Shops", _day(base, day, today), "Wawa", -_dollars(rng.randint(4, 11)))

        # Irregular one-offs.
        for _ in range(rng.randint(20, 24)):
            payee, cat_key, acct_kind, lo, hi = rng.choice(_ONE_OFFS)
            account = {"credit": credit, "checking": checking}[acct_kind]
            day = rng.randint(1, 28)
            add(account, cat_key, _day(base, day, today), payee, -_dollars(rng.randint(lo, hi)))

    return txns


def _load_transactions(db: Session, txns: list[dict]) -> int:
    created = 0
    for index, t in enumerate(txns):
        import_hash = _hash(
            index,
            t["account"].id,
            t["date"].isoformat(),
            t["payee"],
            t["amount_cents"],
        )
        existing = db.scalars(
            select(Transaction).filter_by(import_hash=import_hash)
        ).first()
        if existing is not None:
            continue
        db.add(
            Transaction(
                account_id=t["account"].id,
                category_id=t["category"].id if t["category"] else None,
                date=t["date"],
                payee=t["payee"],
                amount_cents=t["amount_cents"],
                memo=t["memo"],
                cleared=t["cleared"],
                import_hash=import_hash,
            )
        )
        created += 1
    return created


# Demo goals: (Group/Category, kind, target dollars).
_GOALS: list[tuple[str, GoalKind, int]] = [
    ("Savings/Emergency Fund", GoalKind.savings_target, 10_000),
    ("Savings/Vacation Fund", GoalKind.savings_target, 3_000),
    ("Food/Groceries", GoalKind.spending_cap, 800),
    ("Food/Restaurants", GoalKind.spending_cap, 450),
    ("Fun/Entertainment", GoalKind.spending_cap, 300),
]


def _ensure_goals(db: Session, categories: dict[str, Category]) -> None:
    for cat_key, kind, target_dollars in _GOALS:
        category = categories.get(cat_key)
        if category is None:
            continue
        get_or_create(
            db,
            Goal,
            defaults={"target_cents": _dollars(target_dollars), "target_month": None},
            category_id=category.id,
            kind=kind,
        )


def run_seed(db: Session) -> dict[str, int]:
    """Populate the database with demo data. Idempotent."""

    accounts, categories = _ensure_reference_data(db)
    txns = _build_transactions(accounts, categories)
    created = _load_transactions(db, txns)
    _ensure_goals(db, categories)
    db.commit()
    return {"transactions_created": created, "transactions_generated": len(txns)}


def row_counts(db: Session) -> dict[str, int]:
    counts: dict[str, int] = {}
    for model in (
        Account,
        CategoryGroup,
        Category,
        Transaction,
        Allocation,
        CategoryRule,
        Goal,
    ):
        counts[model.__tablename__] = db.scalar(
            select(func.count()).select_from(model)
        )
    return counts


def main() -> None:
    # Seed rows must belong to a user. Resolve one first with an unscoped
    # session, then do the actual seeding inside that user's scope so the
    # before_flush stamper fills user_id automatically.
    from sqlalchemy import select

    from .models import User

    with unscoped_session(reason="seeding must find a user before it has a scope") as lookup:
        user = lookup.scalar(select(User).order_by(User.id))
        if user is None:
            raise SystemExit(
                "No user exists to own seed data. Run `just migrate` with "
                "BOOTSTRAP_EMAIL set, then scripts/set_password.py."
            )
        user_id = user.id

    with user_session(user_id) as db:
        result = run_seed(db)
        counts = row_counts(db)

    print(
        f"Seed complete: {result['transactions_created']} transaction(s) created, "
        f"{result['transactions_generated']} generated."
    )
    print("Row counts per table:")
    for table, count in counts.items():
        print(f"  {table:16} {count}")


if __name__ == "__main__":
    main()

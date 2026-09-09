#!/usr/bin/env python
"""Read-only analysis of pending transactions vs their posted twins.

Purpose: measure F10 (a pending row lingering beside the posted transaction it
should have matched) from real data, and show *why* the current matcher rejects
near-misses — so tolerances are chosen from numbers, not guesses.

This script CHANGES NOTHING: no writes, no migrations. It reuses the live
matcher predicates from ``app.sync.engine`` so the analysis reflects the actual
thresholds in production, not a re-implementation.

Run from ``backend/``:  uv run python scripts/analyze_pending.py
"""

from __future__ import annotations

import difflib
import os
import sys
from collections import Counter
from datetime import date

# Make the backend package importable when run as `python scripts/…`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select

from app.db import SessionLocal
from app.importer import normalize_payee
from app.models import Account, Transaction, TxnSource
from app.sync.engine import (
    _PENDING_MATCH_DAYS,
    _STALE_PENDING_DAYS,
    _similar_description,
    _within_20_percent,
)

# "Plausible twin" = looser than the strict matcher; a human would likely call
# it the same charge. Used only to surface near-misses the matcher rejected.
_PLAUSIBLE_DAYS = _STALE_PENDING_DAYS  # 14
_PLAUSIBLE_AMOUNT_PCT = 50.0
_PLAUSIBLE_DESC_RATIO = 0.60


def amount_delta_pct(pending_cents: int, posted_cents: int) -> float | None:
    if pending_cents == 0:
        return None
    return abs(abs(posted_cents) - abs(pending_cents)) / abs(pending_cents) * 100.0


def desc_ratio(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_payee(a), normalize_payee(b)).ratio()


def _rule() -> None:
    print("-" * 92)


def main() -> None:
    db = SessionLocal()
    today = date.today()

    pending = list(
        db.scalars(
            select(Transaction)
            .where(Transaction.pending.is_(True))
            .order_by(Transaction.account_id, Transaction.date)
        )
    )
    posted = list(
        db.scalars(
            select(Transaction).where(Transaction.pending.is_(False))
        )
    )
    posted_by_account: dict[int, list[Transaction]] = {}
    for t in posted:
        posted_by_account.setdefault(t.account_id, []).append(t)

    account_name = {a.id: a.name for a in db.scalars(select(Account))}

    print("=" * 92)
    print("PENDING TRANSACTION ANALYSIS (read-only)")
    print(f"as of {today.isoformat()}   strict matcher: "
          f"<= {_PENDING_MATCH_DAYS}d, within 20% amount, similar description   "
          f"stale sweep: {_STALE_PENDING_DAYS}d")
    print("=" * 92)

    # ---- Section 1 + 2: every pending row, its age, and its best posted twin.
    print("\n[1+2] CURRENTLY PENDING ROWS AND NEAREST POSTED CANDIDATE (<= 14 days)\n")
    header = (
        f"{'id':>5}  {'account':<16}  {'date':<10}  {'age':>3}  {'amount':>10}  "
        f"{'categ?':>6}   {'twin Δ%':>8}  {'twin sim':>8}  {'strict?':>7}  rejected_by"
    )
    print(header)
    _rule()

    rejected_criteria = Counter()
    n_strict_match = 0
    n_plausible_rejected = 0
    n_no_candidate = 0

    for p in pending:
        age = (today - p.date).days
        categorized = "yes" if p.category_id is not None else "no"

        candidates = [
            q
            for q in posted_by_account.get(p.account_id, [])
            if abs((q.date - p.date).days) <= _PLAUSIBLE_DAYS
        ]

        # Would the strict matcher accept any candidate? (If so, not a linger.)
        strict_hit = next(
            (
                q
                for q in candidates
                if abs((q.date - p.date).days) <= _PENDING_MATCH_DAYS
                and _within_20_percent(q.amount_cents, p.amount_cents)
                and _similar_description(q.description if hasattr(q, "description") else q.payee, p.payee)
            ),
            None,
        )

        # Best plausible twin (looser), for the near-miss breakdown.
        plausible = [
            q
            for q in candidates
            if (amount_delta_pct(p.amount_cents, q.amount_cents) or 999)
            <= _PLAUSIBLE_AMOUNT_PCT
            and desc_ratio(p.payee, q.payee) >= _PLAUSIBLE_DESC_RATIO
        ]
        best = None
        if plausible:
            best = max(plausible, key=lambda q: desc_ratio(p.payee, q.payee))

        twin = strict_hit or best
        delta = amount_delta_pct(p.amount_cents, twin.amount_cents) if twin else None
        sim = desc_ratio(p.payee, twin.payee) if twin else None

        rejected_by = ""
        if strict_hit is not None:
            n_strict_match += 1
            rejected_by = "(would match)"
        elif best is not None:
            n_plausible_rejected += 1
            fails = []
            if abs((best.date - p.date).days) > _PENDING_MATCH_DAYS:
                fails.append("date")
                rejected_criteria["date_window"] += 1
            if not _within_20_percent(best.amount_cents, p.amount_cents):
                fails.append("amount")
                rejected_criteria["amount_tolerance"] += 1
            if not _similar_description(best.payee, p.payee):
                fails.append("description")
                rejected_criteria["description_similarity"] += 1
            rejected_by = "+".join(fails) or "(unknown)"
        else:
            n_no_candidate += 1
            rejected_by = "no candidate"

        print(
            f"{p.id:>5}  {account_name.get(p.account_id, '?')[:16]:<16}  "
            f"{p.date.isoformat():<10}  {age:>3}  {p.amount_cents / 100:>10.2f}  "
            f"{categorized:>6}   "
            f"{(f'{delta:.1f}' if delta is not None else '-'):>8}  "
            f"{(f'{sim:.2f}' if sim is not None else '-'):>8}  "
            f"{('yes' if strict_hit else 'no'):>7}  {rejected_by}"
        )

    if not pending:
        print("(none)")

    # ---- Section 3: distribution of rejections.
    print("\n[3] NEAR-MISS DISTRIBUTION (pending rows with a plausible posted twin "
          "the STRICT matcher rejected)\n")
    print(f"  total currently pending .................. {len(pending)}")
    print(f"  would already match (strict) ............. {n_strict_match}")
    print(f"  plausible twin, rejected by matcher ...... {n_plausible_rejected}")
    print(f"  no candidate within 14 days .............. {n_no_candidate}")
    if n_plausible_rejected:
        print("\n  rejected plausible twins, by failing criterion "
              "(a twin may fail more than one):")
        for crit in ("date_window", "amount_tolerance", "description_similarity"):
            print(f"    {crit:<24} {rejected_criteria.get(crit, 0)}")

    # ---- Section 4: historical sweeps (structurally unmeasurable today).
    print("\n[4] LAST 90 DAYS: PENDING ROWS AGED OUT BY THE 14-DAY SWEEP\n")
    print("  UNMEASURABLE from current data. The stale-pending sweep in")
    print("  engine.apply() HARD-DELETES rows (db.delete), and SyncRun records")
    print("  only added/updated/accounts_synced/errors — not per-row or even")
    print("  aggregate deletes. There is no audit trail, so we cannot say how")
    print("  many swept rows had a plausible twin at deletion time.")
    print("  To measure this we would need one of: (a) soft-delete pending rows")
    print("  (deleted_at) instead of hard delete, or (b) a sync_deletions log,")
    print("  or (c) add a 'deleted' count to SyncRun as a coarse lower bound.")

    print("\n" + "=" * 92)
    if not pending:
        print("NOTE: no pending transactions exist in this database yet (no live")
        print("SimpleFIN sync has populated pending rows). Numbers above are the")
        print("true current state; re-run after real syncs to pick tolerances.")
        print("=" * 92)

    db.close()


if __name__ == "__main__":
    main()

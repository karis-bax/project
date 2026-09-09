"""Sync upsert engine (operates on a Session; provider-agnostic).

Rules enforced here:
1. Callers request an overlapping window (see the router); this module simply
   upserts whatever it is given.
2. Upsert on (account_id, external_id) — an existing row is updated, never
   duplicated.
3. Pending -> posted: id match updates in place; a new posted txn with no id
   match is reconciled against a recent pending row (<=5 days, within 20% on
   amount, similar description) and updates THAT row, keeping its category; a
   pending row older than 14 days that never posted is deleted.
4. Sync owns amount, date, description and pending. It never overwrites the
   category or memo the user assigned.
5. Category rules run only against newly inserted rows.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..importer import normalize_payee
from ..models import Account, CategoryRule, Transaction, TxnSource
from ..rules_engine import Rule, propose_category, sort_rules
from .base import NormalizedAccount, NormalizedTxn

_PENDING_MATCH_DAYS = 5
_STALE_PENDING_DAYS = 14


@dataclass
class ApplyResult:
    accounts_synced: int = 0
    added: int = 0
    updated: int = 0
    deleted: int = 0


def _load_rules(db: Session) -> list[Rule]:
    return sort_rules(
        [
            Rule(
                match_field=r.match_field.value,
                pattern=r.pattern,
                category_id=r.category_id,
                priority=r.priority,
            )
            for r in db.scalars(select(CategoryRule))
        ]
    )


def _similar_description(a: str, b: str) -> bool:
    na, nb = normalize_payee(a), normalize_payee(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _within_20_percent(new_cents: int, pending_cents: int) -> bool:
    # |Δ| <= 20% of the pending amount, using integer math (20% == 1/5).
    return abs(abs(new_cents) - abs(pending_cents)) * 5 <= abs(pending_cents)


def _content_key(account_id: int, posted_date: date, amount_cents: int, description: str) -> str:
    return f"{account_id}|{posted_date.isoformat()}|{amount_cents}|{normalize_payee(description)}"


def _apply_sync_fields(row: Transaction, nt: NormalizedTxn) -> None:
    # Sync owns these; category and memo are left untouched (user-owned).
    row.amount_cents = nt.amount_cents
    row.date = nt.posted_date
    row.payee = nt.description
    row.pending = nt.pending
    row.content_key = _content_key(
        row.account_id, nt.posted_date, nt.amount_cents, nt.description
    )


def _find_pending_match(
    candidates: list[Transaction], nt: NormalizedTxn, matched: set[int]
) -> Transaction | None:
    best: Transaction | None = None
    best_delta = None
    for row in candidates:
        if (
            row.id in matched
            or not row.pending
            or row.source != TxnSource.sync
            or row.deleted_at is not None
        ):
            continue
        if abs((nt.posted_date - row.date).days) > _PENDING_MATCH_DAYS:
            continue
        if not _within_20_percent(nt.amount_cents, row.amount_cents):
            continue
        if not _similar_description(nt.description, row.payee):
            continue
        delta = abs(abs(nt.amount_cents) - abs(row.amount_cents))
        if best is None or delta < best_delta:
            best, best_delta = row, delta
    return best


def apply(
    db: Session,
    accounts: list[NormalizedAccount],
    now: datetime | None = None,
) -> ApplyResult:
    now = now or datetime.now()
    today = now.date()
    rules = _load_rules(db)
    result = ApplyResult()

    for na in accounts:
        local = db.scalar(
            select(Account).where(
                Account.sync_source == "simplefin",
                Account.external_id == na.external_id,
            )
        )
        if local is None:
            continue  # discovered but not linked yet
        result.accounts_synced += 1

        # Include soft-deleted rows: a resync that matches one should REVIVE it
        # (clear deleted_at) rather than insert a duplicate or hit a constraint.
        existing = list(
            db.scalars(
                select(Transaction)
                .where(Transaction.account_id == local.id)
                .execution_options(include_deleted=True)
            )
        )
        by_ext = {t.external_id: t for t in existing if t.external_id}
        matched: set[int] = set()

        def _insert(nt: NormalizedTxn) -> None:
            db.add(
                Transaction(
                    account_id=local.id,
                    external_id=nt.external_id,
                    date=nt.posted_date,
                    payee=nt.description,
                    amount_cents=nt.amount_cents,
                    memo="",
                    cleared=not nt.pending,
                    pending=nt.pending,
                    source=TxnSource.sync,
                    content_key=_content_key(
                        local.id, nt.posted_date, nt.amount_cents, nt.description
                    ),
                    category_id=propose_category(rules, nt.description, ""),
                )
            )
            result.added += 1

        posted_leftovers: list[NormalizedTxn] = []

        for nt in na.transactions:
            row = by_ext.get(nt.external_id)
            if row is not None:
                # external_id match: normal update path (owns amount/date/desc/pending).
                if row.deleted_at is not None:
                    row.deleted_at = None  # revive
                _apply_sync_fields(row, nt)
                if row.id is not None:
                    matched.add(row.id)
                result.updated += 1
                continue

            if not nt.pending:
                candidate = _find_pending_match(existing, nt, matched)
                if candidate is not None:
                    # Pending posted (possibly under a new id, changed amount).
                    candidate.external_id = nt.external_id
                    _apply_sync_fields(candidate, nt)
                    by_ext[nt.external_id] = candidate
                    if candidate.id is not None:
                        matched.add(candidate.id)
                    result.updated += 1
                    continue
                # Posted with no id/pending match: defer to count matching.
                posted_leftovers.append(nt)
                continue

            # Pending with no id match: insert as a new pending row.
            _insert(nt)

        # Count matching for posted leftovers: dedup by content_key WITHOUT a
        # content-unique constraint. Match each leftover to an as-yet-unmatched
        # existing POSTED sync row with the same key (adopting the new id); only
        # the genuine surplus (N_in - N_db) is inserted. Two real identical
        # charges therefore both survive; a reissued id updates in place.
        pool: dict[str, list[Transaction]] = defaultdict(list)
        for t in existing:
            if (
                t.id is not None
                and t.id not in matched
                and t.source == TxnSource.sync
                and not t.pending
                and t.content_key
            ):
                pool[t.content_key].append(t)

        for nt in posted_leftovers:
            key = _content_key(local.id, nt.posted_date, nt.amount_cents, nt.description)
            bucket = pool.get(key)
            if bucket:
                row = bucket.pop(0)
                if row.deleted_at is not None:
                    row.deleted_at = None  # revive a previously-deleted posted row
                row.external_id = nt.external_id
                _apply_sync_fields(row, nt)
                matched.add(row.id)
                result.updated += 1
            else:
                _insert(nt)

        # Soft-delete pending sync rows that never posted and are now stale
        # (rides the same mechanism as user deletes; not a hard delete).
        cutoff = today - timedelta(days=_STALE_PENDING_DAYS)
        for t in existing:
            if (
                t.source == TxnSource.sync
                and t.pending
                and t.deleted_at is None
                and t.date < cutoff
            ):
                t.deleted_at = now
                result.deleted += 1

        local.last_synced_at = now

    db.flush()
    return result

"""Soft delete must survive WRITE paths, not only read paths.

The original guard in test_soft_delete.py enumerated GET routes only: it proved
a soft-deleted transaction vanishes from every read, and never checked that a
write cannot touch one. The session-level filter in app/db.py was gated on
``state.is_select``, so every non-SELECT statement escaped it entirely.
"""

from __future__ import annotations

import datetime as dt
from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    Transaction,
    TxnSource,
)


def _seed(session: Session) -> tuple[Account, Category, Transaction, Transaction]:
    account = Account(
        name="Checking",
        kind=AccountKind.checking,
        opening_balance_cents=0,
        archived=False,
    )
    group = CategoryGroup(name="Food", sort_order=0)
    session.add_all([account, group])
    session.flush()
    category = Category(group_id=group.id, name="Groceries", sort_order=0, archived=False)
    other = Category(group_id=group.id, name="Dining", sort_order=1, archived=False)
    session.add_all([category, other])
    session.flush()

    live = Transaction(
        account_id=account.id,
        category_id=category.id,
        date=date(2026, 3, 10),
        payee="LIVE ROW",
        amount_cents=-2500,
        source=TxnSource.manual,
    )
    deleted = Transaction(
        account_id=account.id,
        category_id=category.id,
        date=date(2026, 3, 11),
        payee="ZZ-DELETED-ROW",
        amount_cents=-9900,
        source=TxnSource.manual,
        deleted_at=dt.datetime(2026, 3, 12, 8, 0, 0),
    )
    session.add_all([live, deleted])
    session.commit()
    return account, other, live, deleted


def _snapshot(session: Session, txn_id: int) -> dict[str, object]:
    """Every column of a row, read past the soft-delete filter."""

    row = session.scalar(
        select(Transaction)
        .where(Transaction.id == txn_id)
        .execution_options(include_deleted=True)
    )
    assert row is not None
    session.refresh(row)
    return {
        c.name: getattr(row, c.name) for c in Transaction.__table__.columns  # type: ignore[union-attr]
    }


def test_bulk_categorize_skips_soft_deleted_ids(
    client: TestClient, session: Session
) -> None:
    """A soft-deleted transaction must not be re-categorized by a bulk write.

    The bulk update issues `update(Transaction).where(id.in_(ids))`, which the
    SELECT-only session filter never constrained.
    """

    _account, other, live, deleted = _seed(session)
    before = _snapshot(session, deleted.id)

    resp = client.post(
        "/api/transactions/bulk-categorize",
        json={"ids": [deleted.id, live.id], "category_id": other.id},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 1, "only the live row is categorizable"
    assert _snapshot(session, deleted.id) == before, "soft-deleted row was modified"
    session.refresh(live)
    assert live.category_id == other.id, "the live row should still be updated"


def test_patch_cannot_modify_a_soft_deleted_transaction(
    client: TestClient, session: Session
) -> None:
    _account, _other, _live, deleted = _seed(session)
    before = _snapshot(session, deleted.id)

    resp = client.patch(f"/api/transactions/{deleted.id}", json={"payee": "CHANGED"})

    assert resp.status_code == 404, resp.text
    assert _snapshot(session, deleted.id) == before


def test_deleting_an_already_deleted_transaction_does_not_extend_retention(
    client: TestClient, session: Session
) -> None:
    """Re-deleting must not advance deleted_at.

    scripts/purge_soft_deleted.py hard-deletes rows whose deleted_at is older
    than the retention window. If DELETE re-stamps an already-deleted row, that
    row's retention clock resets and it can be kept alive indefinitely.
    """

    _account, _other, _live, deleted = _seed(session)
    before = _snapshot(session, deleted.id)

    resp = client.delete(f"/api/transactions/{deleted.id}")

    assert resp.status_code == 404, resp.text
    after = _snapshot(session, deleted.id)
    assert after["deleted_at"] == before["deleted_at"], "retention clock was reset"


def test_session_get_does_not_bypass_the_filter_via_the_identity_map(
    session: Session,
) -> None:
    """Session.get() returns identity-map hits without emitting SQL.

    do_orm_execute never fires on that path, so with_loader_criteria never
    applies and a filtered row comes back anyway. This is why routes must not
    reach for db.get() on a filtered model.
    """

    _account, _other, _live, deleted = _seed(session)
    warm = session.get(Transaction, deleted.id)  # identity map is populated
    assert warm is not None, "precondition: the row is resident in the session"

    fresh = session.scalar(select(Transaction).where(Transaction.id == deleted.id))
    assert fresh is None, "a real SELECT must not return a soft-deleted row"


def test_bulk_categorize_count_excludes_soft_deleted(
    client: TestClient, session: Session
) -> None:
    """The reported count must be rows actually changed."""

    _account, other, _live, deleted = _seed(session)

    resp = client.post(
        "/api/transactions/bulk-categorize",
        json={"ids": [deleted.id], "category_id": other.id},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["updated"] == 0
    assert (
        session.scalar(
            select(func.count())
            .select_from(Transaction)
            .where(Transaction.category_id == other.id)
            .execution_options(include_deleted=True)
        )
        == 0
    )

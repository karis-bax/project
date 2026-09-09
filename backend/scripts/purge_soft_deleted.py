#!/usr/bin/env python
"""Hard-delete transactions that have been soft-deleted for more than 90 days.

The soft-delete safety net is not a trash folder that grows forever. This runs
from the same schedule as the backup job and logs what it purged.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Transaction  # noqa: E402

RETAIN_DAYS = 90


def main() -> int:
    cutoff = datetime.now() - timedelta(days=RETAIN_DAYS)
    db = SessionLocal()
    try:
        doomed = list(
            db.scalars(
                select(Transaction)
                .where(Transaction.deleted_at.is_not(None))
                .where(Transaction.deleted_at < cutoff)
                .execution_options(include_deleted=True)
            )
        )
        for t in doomed:
            print(
                f"purging id={t.id} account={t.account_id} "
                f"amount_cents={t.amount_cents} payee={t.payee!r} "
                f"deleted_at={t.deleted_at.isoformat()}"
            )
        if doomed:
            db.execute(
                delete(Transaction)
                .where(Transaction.id.in_([t.id for t in doomed]))
                .execution_options(include_deleted=True)
            )
            db.commit()
        print(f"Purged {len(doomed)} transaction(s) soft-deleted before {cutoff.date()}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())

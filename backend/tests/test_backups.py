"""Unit tests for backup retention (pure GFS logic)."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.backups.retention import (
    DAILY_KEEP,
    MONTHLY_KEEP,
    WEEKLY_KEEP,
    parse_timestamp,
    select_retention,
)


def _name(dt: datetime) -> str:
    return f"envelope-{dt.strftime('%Y-%m-%dT%H%M%S')}.db.gz.age"


def test_parse_timestamp() -> None:
    assert parse_timestamp("envelope-2026-09-09T142530.db.gz.age") == datetime(
        2026, 9, 9, 14, 25, 30
    )
    assert parse_timestamp("not-a-backup.txt") is None


def test_retention_keeps_gfs_window_and_deletes_the_rest() -> None:
    start = datetime(2026, 9, 9, 2, 30, 0)
    # 400 daily backups, newest first.
    names = [_name(start - timedelta(days=i)) for i in range(400)]

    kept, deleted = select_retention(names)

    # 7 daily + 4 weekly + 12 monthly, de-duplicated across the buckets.
    assert len(kept) <= DAILY_KEEP + WEEKLY_KEEP + MONTHLY_KEEP
    assert len(kept) >= MONTHLY_KEEP  # at least the monthly window survives
    assert kept | deleted == set(names)
    assert kept.isdisjoint(deleted)
    # The most recent backup is always kept.
    assert _name(start) in kept
    # Something old is definitely deleted.
    assert _name(start - timedelta(days=399)) in deleted


def test_retention_empty() -> None:
    assert select_retention([]) == (set(), set())
    assert select_retention(["junk.txt"]) == (set(), set())

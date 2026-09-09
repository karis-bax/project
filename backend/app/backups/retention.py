"""Grandfather-father-son retention over backup artifact names.

Pure logic: no filesystem, no network. The caller lists names at whatever
destination it uses and applies the (kept, deleted) split this returns.

Artifact names look like ``envelope-2026-09-09T142530.db.gz.age``; anything that
does not parse is ignored entirely — neither kept nor deleted. Deleting an
unrecognised file is not this module's business, and a foreign file at the
destination must never be destroyed by a retention sweep.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

# 7 daily + 4 weekly + 12 monthly. Buckets overlap, so the retained set is
# usually smaller than the sum: the newest backup satisfies all three.
DAILY_KEEP = 7
WEEKLY_KEEP = 4
MONTHLY_KEEP = 12

_PREFIX = "envelope-"
_SUFFIX = ".db.gz.age"
_STAMP_FORMAT = "%Y-%m-%dT%H%M%S"


def parse_timestamp(name: str) -> datetime | None:
    """Return the timestamp encoded in an artifact name, or None if it isn't one."""

    if not name.startswith(_PREFIX) or not name.endswith(_SUFFIX):
        return None
    stamp = name[len(_PREFIX) : -len(_SUFFIX)]
    try:
        return datetime.strptime(stamp, _STAMP_FORMAT)
    except ValueError:
        return None


def _newest_per_bucket(
    dated: list[tuple[str, datetime]],
    key: object,
    limit: int,
) -> set[str]:
    """Newest artifact from each of the ``limit`` most recent buckets."""

    seen: dict[object, str] = {}
    for name, when in dated:  # newest first, so the first hit per bucket wins
        bucket = key(when)  # type: ignore[operator]
        if bucket not in seen:
            seen[bucket] = name
    return set(list(seen.values())[:limit])


def select_retention(names: Iterable[str]) -> tuple[set[str], set[str]]:
    """Split artifact names into (kept, deleted) under the GFS policy.

    Unparseable names appear in neither set.
    """

    dated = [(n, ts) for n in names if (ts := parse_timestamp(n)) is not None]
    if not dated:
        return set(), set()

    dated.sort(key=lambda pair: pair[1], reverse=True)

    kept = (
        _newest_per_bucket(dated, lambda d: d.date(), DAILY_KEEP)
        | _newest_per_bucket(dated, lambda d: d.isocalendar()[:2], WEEKLY_KEEP)
        | _newest_per_bucket(dated, lambda d: (d.year, d.month), MONTHLY_KEEP)
    )
    deleted = {name for name, _ in dated} - kept
    return kept, deleted

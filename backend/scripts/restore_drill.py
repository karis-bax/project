#!/usr/bin/env python
"""Restore drill: prove the latest backup actually restores.

Pulls the latest artifact, decrypts (needs the age identity — which in
production lives where the drill runs, not on the backup host), decompresses to a
temp database, runs PRAGMA integrity_check, and compares the restored database
against the live one: identical table set, per-table row counts within 5%, and a
present, non-zero total of amount_cents. Exits non-zero on any failure and
alerts, because a backup you can't restore is not a backup.
"""

from __future__ import annotations

import gzip
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.backups import crypto  # noqa: E402
from app.backups.destinations import destination_from_env  # noqa: E402
from app.backups.retention import parse_timestamp  # noqa: E402
from app.db import DATABASE_URL  # noqa: E402
from scripts.backup import alert  # noqa: E402

ROW_COUNT_TOLERANCE = 0.05


def _db_path() -> Path:
    return Path(DATABASE_URL[len("sqlite:///") :]).resolve()


def _tables(con: sqlite3.Connection) -> set[str]:
    rows = con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {r[0] for r in rows}


def _row_counts(con: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}


def main() -> int:
    identity = os.environ.get("BACKUP_AGE_IDENTITY")
    if not identity or not Path(identity).exists():
        alert("Restore drill: BACKUP_AGE_IDENTITY not available; cannot decrypt.")
        print("Restore drill FAILED: no age identity available", file=sys.stderr)
        return 1

    try:
        destination = destination_from_env(dict(os.environ))
        names = [n for n in destination.list_names() if parse_timestamp(n)]
        if not names:
            raise RuntimeError("No backups found at destination.")
        latest = max(names, key=lambda n: parse_timestamp(n))

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            enc = tmpdir / latest
            destination.download(latest, enc)
            gz = tmpdir / "restored.db.gz"
            crypto.decrypt(enc, gz, Path(identity))
            restored = tmpdir / "restored.db"
            with gzip.open(gz, "rb") as src, open(restored, "wb") as out:
                shutil.copyfileobj(src, out)

            rcon = sqlite3.connect(str(restored))
            lcon = sqlite3.connect(str(_db_path()))
            try:
                integrity = rcon.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    raise RuntimeError(f"integrity_check failed: {integrity}")

                live_tables = _tables(lcon)
                restored_tables = _tables(rcon)
                if live_tables != restored_tables:
                    raise RuntimeError(
                        f"table set mismatch: live-only={live_tables - restored_tables}, "
                        f"restored-only={restored_tables - live_tables}"
                    )

                live_counts = _row_counts(lcon, live_tables)
                restored_counts = _row_counts(rcon, restored_tables)

                print(f"Restored from: {latest}  ({destination.describe()})")
                print(f"integrity_check: {integrity}")
                print(f"{'table':<20}{'live':>10}{'restored':>12}")
                print("-" * 42)
                for table in sorted(live_tables):
                    lv, rv = live_counts[table], restored_counts[table]
                    print(f"{table:<20}{lv:>10}{rv:>12}")
                    tolerance = max(1, int(lv * ROW_COUNT_TOLERANCE))
                    if abs(lv - rv) > tolerance:
                        raise RuntimeError(
                            f"row count for {table} outside 5%: live={lv} restored={rv}"
                        )

                total = rcon.execute(
                    "SELECT COALESCE(SUM(amount_cents), 0) FROM transactions"
                ).fetchone()[0]
                if not total:
                    raise RuntimeError("restored sum(amount_cents) is missing or zero")
                print(f"\nsum(amount_cents) in restored transactions: {total}")
            finally:
                rcon.close()
                lcon.close()

        print("\nRestore drill PASSED.")
        return 0

    except Exception as exc:  # noqa: BLE001
        alert(f"Restore drill failed: {exc}")
        print(f"Restore drill FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

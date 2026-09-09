#!/usr/bin/env python
"""Create an encrypted, off-host-decryptable backup of the Envelope database.

Why not just ``cp`` the SQLite file? A plain copy taken while a write is in
flight can capture a torn page or a half-applied transaction (the -wal/-shm are
separate files), producing a snapshot that fails integrity_check. ``VACUUM
INTO`` writes a NEW, transactionally-consistent database file even mid-write, so
that is what we snapshot.

Pipeline: VACUUM INTO -> gzip -> age-encrypt (to a recipient whose private key
lives OFF this host) -> upload -> GFS retention -> JSON status. Exits non-zero on
any failure, and on failure also writes a log line and fires a desktop
notification, because a silent backup failure is the actual disaster.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.backups import crypto  # noqa: E402
from app.backups.destinations import destination_from_env  # noqa: E402
from app.backups.retention import parse_timestamp, select_retention  # noqa: E402
from app.db import DATABASE_URL  # noqa: E402


def _log_path() -> Path:
    return Path(os.environ.get("BACKUP_LOG", str(Path.home() / ".envelope" / "backup.log")))


def alert(message: str) -> None:
    """Record a failure where a human will see it: log file + desktop toast."""
    log = _log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    with log.open("a") as f:
        f.write(f"{stamp} ALERT {message}\n")
    # Best-effort macOS notification; harmless/no-op elsewhere.
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{message}" with title "Envelope backup"',
            ],
            check=False,
            capture_output=True,
        )
    except FileNotFoundError:
        pass


def _db_path() -> Path:
    if not DATABASE_URL.startswith("sqlite:///"):
        raise RuntimeError(f"Only sqlite backups are supported (got {DATABASE_URL}).")
    return Path(DATABASE_URL[len("sqlite:///") :]).resolve()


def _status_dir() -> Path:
    d = Path(os.environ.get("BACKUP_STATUS_DIR", "./backups/status"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_status(name: str, payload: dict) -> None:
    (_status_dir() / f"{name}.status.json").write_text(json.dumps(payload, indent=2))


def main() -> int:
    started = datetime.now(timezone.utc)
    timestamp = started.strftime("%Y-%m-%dT%H%M%S")
    artifact_name = f"envelope-{timestamp}.db.gz.age"
    status: dict = {"artifact": artifact_name, "started_at": started.isoformat()}

    recipient = os.environ.get("BACKUP_AGE_RECIPIENT")
    if not recipient:
        alert("BACKUP_AGE_RECIPIENT is not set; refusing to write an unencrypted backup.")
        status["ok"] = False
        status["error"] = "missing BACKUP_AGE_RECIPIENT"
        _write_status(artifact_name, status)
        return 1

    try:
        destination = destination_from_env(dict(os.environ))
        db_path = _db_path()

        with tempfile.TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            snapshot = tmpdir / "snapshot.db"
            # Transactionally-consistent snapshot (never a raw cp).
            con = sqlite3.connect(str(db_path))
            try:
                con.execute(f"VACUUM INTO '{snapshot}'")
            finally:
                con.close()

            gz_path = tmpdir / "snapshot.db.gz"
            with open(snapshot, "rb") as raw, gzip.open(gz_path, "wb") as gz:
                shutil.copyfileobj(raw, gz)

            enc_path = tmpdir / artifact_name
            crypto.encrypt(gz_path, enc_path, recipient)

            destination.upload(enc_path, artifact_name)
            status["size_bytes"] = enc_path.stat().st_size

        # GFS retention over whatever is now at the destination.
        names = [n for n in destination.list_names() if parse_timestamp(n)]
        kept, deleted = select_retention(names)
        for name in sorted(deleted):
            destination.delete(name)

        status.update(
            {
                "ok": True,
                "destination": destination.describe(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "kept": sorted(kept),
                "deleted": sorted(deleted),
            }
        )
        _write_status(artifact_name, status)

        print(f"Backup OK: {artifact_name} -> {destination.describe()} "
              f"({status['size_bytes']} bytes)")
        print(f"Retention kept {len(kept)}: {sorted(kept)}")
        print(f"Retention deleted {len(deleted)}: {sorted(deleted)}")
        return 0

    except Exception as exc:  # noqa: BLE001 - any failure must be loud + non-zero
        alert(f"Backup failed: {exc}")
        status.update({"ok": False, "error": str(exc)})
        _write_status(artifact_name, status)
        print(f"Backup FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

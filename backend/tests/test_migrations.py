"""The migration must carry real data across, and fail loudly rather than orphan it.

Runs the actual Alembic revisions against a temporary file database seeded at
the pre-auth revision — not against models.metadata.create_all, which would
never exercise the batch rebuilds where SQLite migrations go wrong.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
PRE_AUTH = "e2bfed7246e2"

_SEED = """
INSERT INTO accounts (name,kind,opening_balance_cents,archived,sync_source,external_id,created_at,updated_at)
  VALUES ('Checking','checking',0,0,'simplefin','ACT-1',datetime('now'),datetime('now'));
INSERT INTO category_groups (name,sort_order,created_at,updated_at)
  VALUES ('Food',0,datetime('now'),datetime('now'));
INSERT INTO categories (group_id,name,sort_order,archived,created_at,updated_at)
  VALUES (1,'Groceries',0,0,datetime('now'),datetime('now'));
INSERT INTO transactions (account_id,category_id,date,payee,amount_cents,memo,cleared,source,pending,import_hash,created_at,updated_at)
  VALUES (1,1,'2026-05-01','PUBLIX',-5230,'',0,'csv',0,'hash-abc',datetime('now'),datetime('now'));
INSERT INTO transactions (account_id,category_id,date,payee,amount_cents,memo,cleared,source,pending,created_at,updated_at)
  VALUES (1,NULL,'2026-05-02','EMPLOYER',300000,'',0,'manual',0,datetime('now'),datetime('now'));
INSERT INTO allocations (month,category_id,amount_cents,created_at,updated_at)
  VALUES ('2026-05',1,20000,datetime('now'),datetime('now'));
"""


def _alembic(db: Path, *args: str, bootstrap_email: str | None = None):
    env = dict(os.environ, DATABASE_URL=f"sqlite:///{db}")
    env.pop("BOOTSTRAP_EMAIL", None)
    if bootstrap_email:
        env["BOOTSTRAP_EMAIL"] = bootstrap_email
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True,
    )


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    db = tmp_path / "envelope.db"
    assert _alembic(db, "upgrade", PRE_AUTH).returncode == 0
    con = sqlite3.connect(db)
    con.executescript(_SEED)
    con.commit()
    con.close()
    return db


def test_migration_refuses_to_orphan_existing_rows(seeded_db: Path) -> None:
    """No BOOTSTRAP_EMAIL + existing data => abort, and change nothing."""

    result = _alembic(seeded_db, "upgrade", "head")
    assert result.returncode != 0
    assert "BOOTSTRAP_EMAIL is not set" in result.stderr

    con = sqlite3.connect(seeded_db)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # Nothing half-applied: the guard runs before any DDL, because SQLite
    # commits DDL statement by statement and a later raise would strand it.
    assert "users" not in tables
    assert con.execute("SELECT count(*) FROM transactions").fetchone()[0] == 2
    con.close()


def test_migration_assigns_every_row_to_the_bootstrap_user(seeded_db: Path) -> None:
    result = _alembic(seeded_db, "upgrade", "head", bootstrap_email="owner@example.com")
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(seeded_db)
    user_id = con.execute("SELECT id FROM users WHERE email='owner@example.com'").fetchone()[0]
    for table in ("accounts", "category_groups", "categories", "transactions", "allocations"):
        total, owned = con.execute(
            f"SELECT count(*), sum(user_id = ?) FROM {table}", (user_id,)  # noqa: S608
        ).fetchone()
        assert total == (owned or 0), f"{table} has rows not owned by the bootstrap user"

    # Money is unchanged, to the cent.
    assert con.execute("SELECT sum(amount_cents) FROM transactions").fetchone()[0] == 294770
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()


def test_bootstrap_user_cannot_log_in_until_a_password_is_set(seeded_db: Path) -> None:
    _alembic(seeded_db, "upgrade", "head", bootstrap_email="owner@example.com")
    con = sqlite3.connect(seeded_db)
    stored = con.execute("SELECT password_hash FROM users").fetchone()[0]
    con.close()

    from app.auth.security import verify_password

    assert stored.startswith("$argon2id$"), "must be a real hash, not a sentinel"
    for guess in ("", "password", "owner@example.com", stored):
        assert verify_password(guess, stored) is False


def test_indexes_survive_the_table_rebuild(seeded_db: Path) -> None:
    """copy_from recreates `transactions` from scratch and drops its indexes."""

    _alembic(seeded_db, "upgrade", "head", bootstrap_email="owner@example.com")
    con = sqlite3.connect(seeded_db)
    idx = {
        r[0]
        for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND tbl_name='transactions' AND name NOT LIKE 'sqlite_%'"
        )
    }
    con.close()
    assert {
        "ix_transactions_user_id",
        "ix_transactions_user_date",
        "ix_transactions_user_account_date",
        "ix_transactions_user_category",
        "ix_transactions_user_content_key",
    } <= idx, f"indexes lost in the rebuild: {sorted(idx)}"


def test_global_import_hash_unique_is_replaced_by_a_per_user_one(seeded_db: Path) -> None:
    """Two users must be able to import the same CSV row."""

    _alembic(seeded_db, "upgrade", "head", bootstrap_email="owner@example.com")
    con = sqlite3.connect(seeded_db)
    sql = con.execute("SELECT sql FROM sqlite_master WHERE name='transactions'").fetchone()[0]
    assert "uq_txn_user_import_hash" in sql
    assert "import_hash VARCHAR," in sql, "column-level UNIQUE was not removed"
    con.close()


def test_sync_run_lock_is_per_user(seeded_db: Path) -> None:
    _alembic(seeded_db, "upgrade", "head", bootstrap_email="owner@example.com")
    con = sqlite3.connect(seeded_db)
    sql = con.execute(
        "SELECT sql FROM sqlite_master WHERE name='uq_sync_run_running'"
    ).fetchone()[0]
    con.close()
    assert "user_id" in sql, "the run lock is still global"
    assert "status = 'running'" in sql, "the partial WHERE clause was lost"


def test_schema_matches_the_models(seeded_db: Path) -> None:
    """`alembic check` must see no difference between models and migrations."""

    _alembic(seeded_db, "upgrade", "head", bootstrap_email="owner@example.com")
    result = _alembic(seeded_db, "check")
    assert result.returncode == 0, (
        "migrations have drifted from the models:\n" + result.stdout + result.stderr
    )


def test_downgrade_round_trip_is_clean(seeded_db: Path) -> None:
    _alembic(seeded_db, "upgrade", "head", bootstrap_email="owner@example.com")
    result = _alembic(seeded_db, "downgrade", PRE_AUTH)
    assert result.returncode == 0, result.stderr

    con = sqlite3.connect(seeded_db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(transactions)")}
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "user_id" not in cols
    assert not {t for t in tables if t.startswith("_alembic_tmp")}, "temp table left behind"
    assert con.execute("SELECT count(*) FROM transactions").fetchone()[0] == 2
    assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    con.close()

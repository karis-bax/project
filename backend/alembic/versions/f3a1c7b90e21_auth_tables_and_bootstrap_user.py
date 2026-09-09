"""auth tables and bootstrap user

Revision ID: f3a1c7b90e21
Revises: e2bfed7246e2
Create Date: 2026-09-09

Part 1 of 2. Creates the auth tables and, if this database already holds data,
the bootstrap user that will own it. Split from the user_id backfill so that a
failure in part 2 leaves these in place and the migration can be re-run after
fixing the environment.

The bootstrap user is created with a password hash that nothing can match. Run
``scripts/set_password.py`` to set a real one. That keeps the migration
non-interactive and puts no plaintext password into the environment, shell
history, or a captured migration log.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "f3a1c7b90e21"
down_revision = "e2bfed7246e2"
branch_labels = None
depends_on = None

# Tables whose rows must end up owned by somebody.
_OWNED_TABLES = (
    "accounts",
    "category_groups",
    "categories",
    "transactions",
    "allocations",
    "category_rules",
    "goals",
    "sync_runs",
)


def _existing_rows(bind: sa.engine.Connection) -> int:
    total = 0
    for table in _OWNED_TABLES:
        total += bind.execute(
            sa.text(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
        ).scalar_one()
    return total


def upgrade() -> None:
    # Checked BEFORE any DDL: SQLite commits DDL statement by statement, so
    # raising after create_table would leave the tables behind while Alembic
    # still considers the revision unapplied — and the re-run would then fail
    # with "table already exists" instead of the message below.
    bind = op.get_bind()
    existing = _existing_rows(bind)
    email = (os.environ.get("BOOTSTRAP_EMAIL") or "").strip().lower()

    if existing and not email:
        raise RuntimeError(
            f"This database holds {existing} row(s) across the owned tables, but "
            "BOOTSTRAP_EMAIL is not set. Refusing to continue: the next "
            "revision would have no user to assign them to and they would be "
            "orphaned. Set BOOTSTRAP_EMAIL=you@example.com and re-run."
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "token_families",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_reason", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_token_families_user_id", "token_families", ["user_id"])

    for name in ("access_tokens", "refresh_tokens"):
        columns = [
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("family_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
            sa.ForeignKeyConstraint(["family_id"], ["token_families.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        ]
        if name == "refresh_tokens":
            columns.insert(6, sa.Column("used_at", sa.DateTime(), nullable=True))
            columns.insert(7, sa.Column("replaced_by_id", sa.Integer(), nullable=True))
            columns.append(
                sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"])
            )
        op.create_table(name, *columns)
        op.create_index(f"ix_{name}_token_hash", name, ["token_hash"], unique=True)
        op.create_index(f"ix_{name}_family_id", name, ["family_id"])
        op.create_index(f"ix_{name}_user_id", name, ["user_id"])

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        # A plain string, NOT a foreign key: attempts are recorded for every
        # submitted address whether or not an account exists, or the lockout
        # itself reveals which addresses are real.
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("successful", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.create_index(
        "ix_login_attempts_email_created", "login_attempts", ["email", "created_at"]
    )

    # --- bootstrap user ---------------------------------------------------
    if not email:
        # Fresh or empty database (a new checkout, CI). Nothing to own, so no
        # user is invented — requiring the env var here would break every
        # clean setup.
        return

    # Imported from the app so the hash parameters cannot drift from the ones
    # the login path uses. alembic/env.py already imports app.db and app.models.
    from app.auth.security import unusable_password_hash

    now = datetime.now(tz=UTC).replace(tzinfo=None)
    bind.execute(
        sa.text(
            "INSERT INTO users (email, password_hash, is_active, created_at, "
            "updated_at) VALUES (:email, :hash, 1, :now, :now)"
        ),
        {"email": email, "hash": unusable_password_hash(), "now": now},
    )
    print("=" * 70)
    print(f"Bootstrap user created: {email}")
    print("It has NO usable password yet. Set one with:")
    print("    uv run python scripts/set_password.py")
    print("Then move the SimpleFIN credential to that user with:")
    print("    uv run python scripts/migrate_keyring_to_user.py <user_id>")
    print("=" * 70)


def downgrade() -> None:
    op.drop_index("ix_login_attempts_email_created", table_name="login_attempts")
    op.drop_table("login_attempts")
    for name in ("refresh_tokens", "access_tokens"):
        op.drop_index(f"ix_{name}_user_id", table_name=name)
        op.drop_index(f"ix_{name}_family_id", table_name=name)
        op.drop_index(f"ix_{name}_token_hash", table_name=name)
        op.drop_table(name)
    op.drop_index("ix_token_families_user_id", table_name="token_families")
    op.drop_table("token_families")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")

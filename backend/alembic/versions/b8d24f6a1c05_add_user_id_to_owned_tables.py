"""add user_id to every owned table

Revision ID: b8d24f6a1c05
Revises: f3a1c7b90e21
Create Date: 2026-09-09

Part 2 of 2. Adds the tenant column to all eight owned tables and rebuilds the
three constraints that were globally unique and become cross-user collisions
(or oracles) under multi-user.

Three-step per table under batch mode: add nullable -> backfill -> set NOT NULL
plus the FK and index. SQLite rebuilds the table for each batch block, so this
is two full copies of `transactions`; fine at personal-budget scale, but worth
knowing before running it on a large database.

`transactions` and `accounts` are rebuilt with an explicit `copy_from` because
`transactions.import_hash` carried a column-level `unique=True`, which SQLite
renders as an UNNAMED unique index that batch mode cannot drop by name.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b8d24f6a1c05"
down_revision = "f3a1c7b90e21"
branch_labels = None
depends_on = None

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


def upgrade() -> None:
    bind = op.get_bind()

    # Pre-flight: existing FK violations must surface here, as an aborted
    # migration, rather than as mysterious runtime errors after the app starts
    # enforcing foreign keys.
    violations = bind.execute(sa.text("PRAGMA foreign_key_check")).fetchall()
    if violations:
        raise RuntimeError(
            f"Database has {len(violations)} pre-existing foreign key "
            f"violation(s); fix them before adding more FKs: {violations[:5]}"
        )

    owner_id = bind.execute(
        sa.text("SELECT id FROM users ORDER BY id LIMIT 1")
    ).scalar()

    # --- step 1: add nullable ---------------------------------------------
    for table in _OWNED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))

    # --- step 2: backfill, or fail loudly ---------------------------------
    # Revision A checked this too, but it only counted three tables and only at
    # that moment. Re-check every table this revision is about to constrain: an
    # orphaned row must abort the migration, never end up owned by nobody.
    for table in _OWNED_TABLES:
        rows = bind.execute(
            sa.text(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
        ).scalar_one()
        if rows and owner_id is None:
            raise RuntimeError(
                f"{table} holds {rows} row(s) but no user exists to own them. "
                "Set BOOTSTRAP_EMAIL and re-run the previous revision "
                "(f3a1c7b90e21) before this one."
            )
        if owner_id is not None:
            bind.execute(
                sa.text(f"UPDATE {table} SET user_id = :owner"),  # noqa: S608
                {"owner": owner_id},
            )

    # --- step 3: NOT NULL + FK + index ------------------------------------
    for table in _OWNED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch:
            batch.alter_column(
                "user_id", existing_type=sa.Integer(), nullable=False
            )
            batch.create_foreign_key(
                f"fk_{table}_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
            )
            batch.create_index(f"ix_{table}_user_id", ["user_id"])

    # --- constraint rebuilds ----------------------------------------------
    # accounts: two users may bank at the same institution and see the same
    # external id. Globally unique, this also let one user's link silently
    # steal another's account.
    with op.batch_alter_table("accounts", schema=None) as batch:
        batch.drop_constraint("uq_account_sync_external", type_="unique")
        batch.create_unique_constraint(
            "uq_account_sync_external", ["user_id", "sync_source", "external_id"]
        )

    # transactions.import_hash: drop the unnamed column-level UNIQUE by
    # rebuilding the table from an explicit definition, then re-add it scoped
    # to the user.
    with op.batch_alter_table(
        "transactions", copy_from=_transactions_target(), schema=None
    ) as batch:
        batch.create_unique_constraint(
            "uq_txn_user_import_hash", ["user_id", "import_hash"]
        )

    # The copy_from rebuild recreates the table from the definition above, which
    # means every index on `transactions` is dropped with the old table. They
    # have to be recreated explicitly or the app silently loses them — a
    # performance regression with no error and no failing test.
    #
    # They come back user_id-first, since the tenant filter is now the leading
    # predicate on every query that touches this table.
    op.create_index("ix_transactions_user_id", "transactions", ["user_id"])
    op.create_index("ix_transactions_user_date", "transactions", ["user_id", "date"])
    op.create_index(
        "ix_transactions_user_account_date",
        "transactions",
        ["user_id", "account_id", "date"],
    )
    op.create_index(
        "ix_transactions_user_category", "transactions", ["user_id", "category_id"]
    )
    op.create_index(
        "ix_transactions_user_content_key", "transactions", ["user_id", "content_key"]
    )

    # sync_runs: the partial unique index was a GLOBAL run lock — one user's
    # running sync made everyone else's 409. The sqlite_where clause must be
    # re-declared explicitly; losing it would turn this into a unique index on
    # status alone and break sync entirely.
    op.drop_index("uq_sync_run_running", table_name="sync_runs")
    op.create_index(
        "uq_sync_run_running",
        "sync_runs",
        ["user_id", "status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )


def _transactions_target() -> sa.Table:
    """The desired shape of `transactions`, WITHOUT the unnamed unique.

    Batch mode otherwise reflects the existing table and faithfully recreates
    the constraint we are trying to remove.
    """

    meta = sa.MetaData()
    return sa.Table(
        "transactions",
        meta,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("account_id", sa.Integer(), sa.ForeignKey("accounts.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("payee", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("memo", sa.String(), nullable=False, server_default=""),
        sa.Column("cleared", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("import_hash", sa.String(), nullable=True),
        sa.Column("external_id", sa.String(), nullable=True),
        sa.Column("content_key", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("pending", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.UniqueConstraint("account_id", "external_id", name="uq_txn_account_external"),
        # Named and CASCADE-ing, matching the model. An unnamed FK here would
        # drift from OwnedMixin and leave downgrade unable to drop it by name.
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_transactions_user_id",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    """Reverse the change.

    Lossy by design once a second user exists: restoring the global unique
    constraints will fail if two users hold what are now legitimately distinct
    rows. Those failures are checked for explicitly so they surface as a clear
    message rather than an opaque IntegrityError.
    """

    bind = op.get_bind()

    clashes = bind.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT sync_source, external_id FROM accounts "
            "WHERE sync_source IS NOT NULL GROUP BY sync_source, external_id "
            "HAVING count(*) > 1)"
        )
    ).scalar_one()
    if clashes:
        raise RuntimeError(
            f"{clashes} external id(s) are linked by more than one user. "
            "Downgrading would restore a global unique constraint they violate. "
            "Remove the duplicate links first."
        )

    running = bind.execute(
        sa.text("SELECT count(*) FROM sync_runs WHERE status = 'running'")
    ).scalar_one()
    if running > 1:
        raise RuntimeError(
            f"{running} sync runs are in progress; the global run lock allows "
            "only one. Wait for them to finish before downgrading."
        )

    op.drop_index("uq_sync_run_running", table_name="sync_runs")
    op.create_index(
        "uq_sync_run_running",
        "sync_runs",
        ["status"],
        unique=True,
        sqlite_where=sa.text("status = 'running'"),
    )

    with op.batch_alter_table("transactions", schema=None) as batch:
        batch.drop_constraint("uq_txn_user_import_hash", type_="unique")

    with op.batch_alter_table("accounts", schema=None) as batch:
        batch.drop_constraint("uq_account_sync_external", type_="unique")
        batch.create_unique_constraint(
            "uq_account_sync_external", ["sync_source", "external_id"]
        )

    for name in (
        "ix_transactions_user_content_key",
        "ix_transactions_user_category",
        "ix_transactions_user_account_date",
        "ix_transactions_user_date",
    ):
        op.drop_index(name, table_name="transactions")
    op.create_index("ix_transactions_date", "transactions", ["date"])
    op.create_index(
        "ix_transactions_account_id_date", "transactions", ["account_id", "date"]
    )
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
    op.create_index("ix_transactions_content_key", "transactions", ["content_key"])

    op.drop_index("ix_transactions_user_id", table_name="transactions")

    for table in _OWNED_TABLES:
        with op.batch_alter_table(table, schema=None) as batch:
            if table != "transactions":
                batch.drop_index(f"ix_{table}_user_id")
            batch.drop_constraint(f"fk_{table}_user_id", type_="foreignkey")
            batch.drop_column("user_id")

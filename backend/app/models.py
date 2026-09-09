"""SQLAlchemy 2.0 declarative models for Envelope.

Conventions (see ``.cursor/rules/stack.mdc``):
- Every model has an integer ``id`` primary key plus ``created_at`` / ``updated_at``.
- Money is a signed integer number of cents named ``amount_cents``: outflows are
  negative, inflows are positive. No floats, Decimals, or strings for money.
- Dates are stored as ``Date``; budget months are ``YYYY-MM`` strings.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from .db import Base


class AccountKind(enum.Enum):
    checking = "checking"
    savings = "savings"
    credit = "credit"
    cash = "cash"


class RuleField(enum.Enum):
    payee = "payee"
    memo = "memo"


class GoalKind(enum.Enum):
    savings_target = "savings_target"
    spending_cap = "spending_cap"


class TxnSource(enum.Enum):
    manual = "manual"
    csv = "csv"
    sync = "sync"


class SyncStatus(enum.Enum):
    running = "running"
    ok = "ok"
    partial = "partial"
    failed = "failed"


class OpeningBalanceSource(enum.Enum):
    entered = "entered"
    derived_at_link = "derived_at_link"


class TimestampMixin:
    """Adds ``created_at`` / ``updated_at`` columns to a model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OwnedMixin:
    """Rows that belong to exactly one user.

    Adding this mixin to a model is the ONLY thing needed to bring it under
    tenant scoping: ``app.db.owned_mappers()`` discovers models by subclass, so
    there is no registry to keep in sync. ``test_every_model_is_tenant_owned``
    fails if a new model forgets it.
    """

    @declared_attr
    def user_id(cls) -> Mapped[int]:  # noqa: N805
        return mapped_column(
            ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
        )


class User(TimestampMixin, Base):
    """A person with a login. Deliberately NOT OwnedMixin — a user owns rows,
    it is not owned."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stored already normalized (stripped + lowercased); see auth.security.
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )


class TokenFamily(TimestampMixin, Base):
    """One login session's chain of rotating refresh tokens.

    Revocation is a single row write here, and both token tables carry
    ``family_id``, so revoking a family also kills its live access tokens —
    which is what makes "reuse forces re-login" true immediately rather than
    true within the access-token TTL.
    """

    __tablename__ = "token_families"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 'logout' | 'reuse_detected' | 'password_change'
    revoked_reason: Mapped[str | None] = mapped_column(String, nullable=True)


class AccessToken(TimestampMixin, Base):
    """Short-lived opaque bearer token. Stored as sha256, never raw."""

    __tablename__ = "access_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("token_families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class RefreshToken(TimestampMixin, Base):
    """Long-lived rotating token. Stored as sha256, never raw.

    ``used_at`` is the reuse pivot: presenting a token that has already been
    rotated means either a client replay or a stolen token, and either way the
    whole family is revoked.
    """

    __tablename__ = "refresh_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_id: Mapped[int] = mapped_column(
        ForeignKey("token_families.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replaced_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("refresh_tokens.id"), nullable=True
    )


class LoginAttempt(Base):
    """One recorded login attempt, for rate limiting.

    ``email`` is a plain string, NOT a foreign key, and a row is written for
    every failed attempt whether or not that address has an account. This is
    the whole point: if attempts were keyed on a user id, only real accounts
    could be counted and the limiter itself would become a perfect
    account-existence oracle — 429 means the address exists, 401 means it does
    not — undoing the timing equalisation in auth.security.

    Deliberately not TimestampMixin: that ``created_at`` uses
    ``server_default=func.now()`` (SQLite UTC) while the window comparison is
    computed in Python. One clock only.
    """

    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_created", "email", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    successful: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Account(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        # Per user: two people may bank at the same institution and see the
        # same external id. Globally unique, this also let one user's link
        # silently steal another's account.
        UniqueConstraint(
            "user_id", "sync_source", "external_id", name="uq_account_sync_external"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[AccountKind] = mapped_column(
        SAEnum(AccountKind, name="account_kind"), nullable=False
    )
    opening_balance_cents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    # Bank-sync linkage (null for manual accounts).
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sync_source: Mapped[str | None] = mapped_column(String, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    # How opening_balance_cents was set. ``derived_at_link`` means it was
    # anchored to the bank's reported balance at link time (not a verified
    # full-history figure); any later divergence is real signal.
    opening_balance_source: Mapped[OpeningBalanceSource] = mapped_column(
        SAEnum(OpeningBalanceSource, name="opening_balance_source"),
        nullable=False,
        default=OpeningBalanceSource.entered,
        server_default="entered",
    )
    opening_balance_derived_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class CategoryGroup(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "category_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    categories: Mapped[list[Category]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class Category(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("category_groups.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    archived: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    group: Mapped[CategoryGroup] = relationship(back_populates="categories")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="category"
    )


class Transaction(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        # user_id leads every index: the tenant filter is the first predicate
        # on every query that touches this table.
        Index("ix_transactions_user_date", "user_id", "date"),
        Index("ix_transactions_user_account_date", "user_id", "account_id", "date"),
        Index("ix_transactions_user_category", "user_id", "category_id"),
        # Content-match key for posted-transaction dedup on resync (see the sync
        # engine): (account_id, posted_date, amount_cents, normalized_payee).
        Index("ix_transactions_user_content_key", "user_id", "content_key"),
        # SimpleFIN ids are unique only within an account, not globally.
        UniqueConstraint(
            "account_id", "external_id", name="uq_txn_account_external"
        ),
        UniqueConstraint("user_id", "import_hash", name="uq_txn_user_import_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id"), nullable=False
    )
    # A NULL category_id means the transaction is uncategorized. The budget
    # engine (added later) treats positive uncategorized amounts as income.
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id"), nullable=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    payee: Mapped[str] = mapped_column(String, nullable=False)
    # Signed integer cents: outflows negative, inflows positive.
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    memo: Mapped[str] = mapped_column(String, nullable=False, default="")
    cleared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    # Unique per user, not globally. The hash preimage already contains the
    # globally-unique account_id, so this is defence in depth rather than a
    # live fix — but a global unique on a user-derived value is a latent
    # cross-tenant collision if that formula ever changes.
    import_hash: Mapped[str | None] = mapped_column(String, nullable=True)

    # Provenance and bank-sync fields.
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # (account_id, posted_date, amount_cents, normalized payee) — used to
    # count-match posted transactions across resyncs without a content-unique
    # constraint (two genuine identical charges must both survive).
    content_key: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[TxnSource] = mapped_column(
        SAEnum(TxnSource, name="txn_source"),
        nullable=False,
        default=TxnSource.manual,
        server_default="manual",
    )
    pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    # Soft delete: a set timestamp hides the row from every read path (enforced
    # at the Session level; see db.py). NULL means live.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    account: Mapped[Account] = relationship(back_populates="transactions")
    category: Mapped[Category | None] = relationship(
        back_populates="transactions"
    )


class Allocation(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "allocations"
    __table_args__ = (
        UniqueConstraint("month", "category_id", name="uq_allocation_month_category"),
        Index("ix_allocations_month", "month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Budget month as a "YYYY-MM" string.
    month: Mapped[str] = mapped_column(String, nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(Integer, nullable=False)

    category: Mapped[Category] = relationship()


class CategoryRule(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "category_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    match_field: Mapped[RuleField] = mapped_column(
        SAEnum(RuleField, name="rule_field"), nullable=False
    )
    # ``pattern`` is a case-insensitive SUBSTRING match against the chosen
    # field (not a regular expression).
    pattern: Mapped[str] = mapped_column(String, nullable=False)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    category: Mapped[Category] = relationship()


class Goal(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id"), nullable=False
    )
    kind: Mapped[GoalKind] = mapped_column(
        SAEnum(GoalKind, name="goal_kind"), nullable=False
    )
    target_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    # Optional target budget month as a "YYYY-MM" string.
    target_month: Mapped[str | None] = mapped_column(String, nullable=True)

    category: Mapped[Category] = relationship()


class SyncRun(OwnedMixin, TimestampMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        # Run lock: at most one run may be in progress at a time. The partial
        # unique index lets a second concurrent run fail fast (409) instead of
        # racing into a 500.
        # Per user: a global lock meant one user's running sync 409'd
        # everyone else's.
        Index(
            "uq_sync_run_running",
            "user_id",
            "status",
            unique=True,
            sqlite_where=text("status = 'running'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[SyncStatus] = mapped_column(
        SAEnum(SyncStatus, name="sync_status"), nullable=False
    )
    accounts_synced: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    swept_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # errlist entries surfaced from the provider (list of {message, ...}).
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

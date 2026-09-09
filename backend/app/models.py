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
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    ok = "ok"
    partial = "partial"
    failed = "failed"


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


class Account(TimestampMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint(
            "sync_source", "external_id", name="uq_account_sync_external"
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

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", cascade="all, delete-orphan"
    )


class CategoryGroup(TimestampMixin, Base):
    __tablename__ = "category_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    categories: Mapped[list[Category]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )


class Category(TimestampMixin, Base):
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


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        Index("ix_transactions_date", "date"),
        Index("ix_transactions_account_id_date", "account_id", "date"),
        Index("ix_transactions_category_id", "category_id"),
        # SimpleFIN ids are unique only within an account, not globally.
        UniqueConstraint(
            "account_id", "external_id", name="uq_txn_account_external"
        ),
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
    import_hash: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True
    )

    # Provenance and bank-sync fields.
    external_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[TxnSource] = mapped_column(
        SAEnum(TxnSource, name="txn_source"),
        nullable=False,
        default=TxnSource.manual,
        server_default="manual",
    )
    pending: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )

    account: Mapped[Account] = relationship(back_populates="transactions")
    category: Mapped[Category | None] = relationship(
        back_populates="transactions"
    )


class Allocation(TimestampMixin, Base):
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


class CategoryRule(TimestampMixin, Base):
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


class Goal(TimestampMixin, Base):
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


class SyncRun(TimestampMixin, Base):
    __tablename__ = "sync_runs"

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
    # errlist entries surfaced from the provider (list of {message, ...}).
    errors: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

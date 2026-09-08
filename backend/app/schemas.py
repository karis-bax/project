"""Pydantic v2 request/response models for Envelope.

Money fields are signed integer cents (``amount_cents``); formatting to dollars
happens only in the React UI. Dates are ISO ``YYYY-MM-DD``; budget months are
``YYYY-MM`` strings.
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from .models import AccountKind, GoalKind, RuleField

MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


class ORMModel(BaseModel):
    """Base for response models read from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class TimestampsMixin(BaseModel):
    created_at: dt.datetime
    updated_at: dt.datetime


# --- Account ---------------------------------------------------------------


class AccountBase(BaseModel):
    name: str
    kind: AccountKind
    opening_balance_cents: int = 0
    archived: bool = False


class AccountCreate(AccountBase):
    pass


class AccountUpdate(BaseModel):
    name: str | None = None
    kind: AccountKind | None = None
    opening_balance_cents: int | None = None
    archived: bool | None = None


class AccountRead(ORMModel, TimestampsMixin, AccountBase):
    id: int


# --- CategoryGroup ---------------------------------------------------------


class CategoryGroupBase(BaseModel):
    name: str
    sort_order: int = 0


class CategoryGroupCreate(CategoryGroupBase):
    pass


class CategoryGroupRead(ORMModel, TimestampsMixin, CategoryGroupBase):
    id: int


# --- Category --------------------------------------------------------------


class CategoryBase(BaseModel):
    group_id: int
    name: str
    sort_order: int = 0
    archived: bool = False


class CategoryCreate(CategoryBase):
    pass


class CategoryRead(ORMModel, TimestampsMixin, CategoryBase):
    id: int


# --- Transaction -----------------------------------------------------------


class TransactionBase(BaseModel):
    account_id: int
    # None means uncategorized; positive uncategorized amounts are income.
    category_id: int | None = None
    date: dt.date
    payee: str
    amount_cents: int
    memo: str = ""
    cleared: bool = False
    import_hash: str | None = None


class TransactionCreate(TransactionBase):
    pass


class TransactionUpdate(BaseModel):
    account_id: int | None = None
    category_id: int | None = None
    date: dt.date | None = None
    payee: str | None = None
    amount_cents: int | None = None
    memo: str | None = None
    cleared: bool | None = None
    import_hash: str | None = None


class TransactionRead(ORMModel, TimestampsMixin, TransactionBase):
    id: int


# --- Allocation ------------------------------------------------------------


class AllocationBase(BaseModel):
    month: str = Field(pattern=MONTH_PATTERN)
    category_id: int
    amount_cents: int


class AllocationCreate(AllocationBase):
    pass


class AllocationRead(ORMModel, TimestampsMixin, AllocationBase):
    id: int


# --- CategoryRule ----------------------------------------------------------


class CategoryRuleBase(BaseModel):
    match_field: RuleField
    pattern: str
    category_id: int
    priority: int = 0


class CategoryRuleCreate(CategoryRuleBase):
    pass


class CategoryRuleRead(ORMModel, TimestampsMixin, CategoryRuleBase):
    id: int


# --- Goal ------------------------------------------------------------------


class GoalBase(BaseModel):
    category_id: int
    kind: GoalKind
    target_cents: int
    target_month: str | None = Field(default=None, pattern=MONTH_PATTERN)


class GoalCreate(GoalBase):
    pass


class GoalRead(ORMModel, TimestampsMixin, GoalBase):
    id: int

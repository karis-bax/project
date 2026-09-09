"""Pydantic v2 request/response models for Envelope.

Money fields are signed integer cents (``amount_cents``); formatting to dollars
happens only in the React UI. Dates are ISO ``YYYY-MM-DD``; budget months are
``YYYY-MM`` strings.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

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
    pending: bool = False
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


# --- API responses / requests ---------------------------------------------


class HealthResponse(BaseModel):
    status: str
    time: dt.datetime


class CategoryGroupWithCategories(ORMModel, TimestampsMixin, CategoryGroupBase):
    id: int
    categories: list[CategoryRead]


class TransactionWithRelations(TransactionRead):
    account: AccountRead
    category: CategoryRead | None = None


class TransactionListResponse(BaseModel):
    items: list[TransactionWithRelations]
    next_cursor: str | None = None


class CountResponse(BaseModel):
    count: int


class PayeeSuggestion(BaseModel):
    payee: str
    suggested_category_id: int | None = None
    count: int


class BulkCategorizeRequest(BaseModel):
    ids: list[int]
    category_id: int | None = None


class BulkCategorizeResponse(BaseModel):
    updated: int


class DeletedResponse(BaseModel):
    id: int
    deleted: bool


class GroupReorderRequest(BaseModel):
    group_ids: list[int]


class AllocationUpsertRequest(BaseModel):
    amount_cents: int


class CopyFromPreviousResponse(BaseModel):
    month: str
    source_month: str
    copied: int


# Budget month-view response models (mirror ``budget.py`` dataclasses).


class CategoryBudgetRow(ORMModel):
    id: int
    name: str
    assigned_cents: int
    activity_cents: int
    available_cents: int
    pending_cents: int = 0


class GroupBudget(ORMModel):
    id: int
    name: str
    categories: list[CategoryBudgetRow]
    assigned_cents: int
    activity_cents: int
    available_cents: int
    pending_cents: int = 0


class MonthBudget(ORMModel):
    month: str
    groups: list[GroupBudget]
    income_cents: int
    assigned_cents: int
    activity_cents: int
    available_cents: int
    left_to_assign_cents: int
    pending_cents: int = 0


# --- CSV import ------------------------------------------------------------


class ImportMapping(BaseModel):
    amount_shape: Literal["signed", "debit_credit", "amount_type"] = "signed"
    date_col: int | None = None
    payee_col: int | None = None
    memo_col: int | None = None
    amount_col: int | None = None
    debit_col: int | None = None
    credit_col: int | None = None
    type_col: int | None = None


class ImportPreviewRow(BaseModel):
    row_index: int
    date: str | None
    payee: str
    amount_cents: int | None
    memo: str
    proposed_category_id: int | None = None
    is_duplicate: bool = False
    importable: bool = False
    import_hash: str | None = None
    warnings: list[str] = []


class ImportPreviewResponse(BaseModel):
    token: str
    account_id: int
    delimiter: str
    has_header: bool
    columns: list[str]
    mapping: ImportMapping
    raw_sample: list[list[str]]
    rows: list[ImportPreviewRow]
    warnings: list[str] = []


class ImportRemapRequest(BaseModel):
    token: str
    mapping: ImportMapping


class ImportCommitRow(BaseModel):
    date: str
    payee: str
    amount_cents: int
    memo: str = ""
    category_id: int | None = None
    is_duplicate: bool = False


class ImportCommitRequest(BaseModel):
    token: str
    rows: list[ImportCommitRow]
    skip_duplicates: bool = True


class ImportCommitResponse(BaseModel):
    imported: int
    skipped_duplicate: int
    failed: int


# --- Rules -----------------------------------------------------------------


class RuleReorderRequest(BaseModel):
    rule_ids: list[int]


class RuleApplyResponse(BaseModel):
    changed: int


# --- Bank sync -------------------------------------------------------------


class SyncClaimRequest(BaseModel):
    setup_token: str


class SyncAccountStatus(BaseModel):
    external_id: str
    name: str
    org_name: str
    currency: str
    reported_balance_cents: int | None = None
    balance_date: str | None = None
    linked_account_id: int | None = None
    local_account_name: str | None = None
    computed_balance_cents: int | None = None
    last_synced_at: dt.datetime | None = None
    opening_balance_source: str | None = None
    mismatch: bool = False


class SyncCreateAccount(BaseModel):
    name: str
    kind: AccountKind


class SyncLinkRequest(BaseModel):
    external_id: str
    account_id: int | None = None
    create_as: SyncCreateAccount | None = None


class SyncRunRequest(BaseModel):
    days: int = 30


class SyncRunRead(ORMModel):
    id: int
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    status: Literal["ok", "partial", "failed"]
    accounts_synced: int
    added: int
    updated: int
    swept_count: int = 0
    errors: list = []


# --- Insights --------------------------------------------------------------


class CategorySpend(BaseModel):
    id: int
    name: str
    spent_cents: int
    compare_cents: int


class GroupSpend(BaseModel):
    id: int
    name: str
    spent_cents: int
    compare_cents: int
    categories: list[CategorySpend]


class ByCategoryResponse(BaseModel):
    month: str
    compare_to: str
    total_spent_cents: int
    total_compare_cents: int
    groups: list[GroupSpend]


class TrendPoint(BaseModel):
    month: str
    spent_cents: int


class TrendCategory(BaseModel):
    id: int
    name: str
    points: list[TrendPoint]
    current_month: str
    mean_cents: int
    stddev_cents: int
    is_outlier: bool
    reason: str | None = None


class TrendsResponse(BaseModel):
    months: list[str]
    categories: list[TrendCategory]


class BurnPoint(BaseModel):
    day: int
    cumulative_cents: int


class BurnSeries(BaseModel):
    month: str
    points: list[BurnPoint]


class BurnResponse(BaseModel):
    month: str
    days_in_month: int
    as_of_day: int
    current: list[BurnPoint]
    history: list[BurnSeries]
    projected_total_cents: int | None = None
    assumption: str


class RecurringItem(BaseModel):
    payee: str
    category_id: int | None = None
    category_name: str | None = None
    average_amount_cents: int
    cadence_days: int
    occurrences: int
    last_date: str
    next_expected_date: str
    next_expected_amount_cents: int


class RecurringResponse(BaseModel):
    items: list[RecurringItem]
    total_committed_monthly_cents: int

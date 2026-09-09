/**
 * TypeScript interfaces mirroring backend/app/schemas.py field for field.
 *
 * Conventions from the backend:
 * - Money is a signed integer number of cents (`amount_cents`).
 * - `date` fields are ISO `YYYY-MM-DD` strings; `month` fields are `YYYY-MM`.
 * - `created_at` / `updated_at` are ISO datetime strings.
 */

// --- Enums (mirror app/models.py) ------------------------------------------

export type AccountKind = 'checking' | 'savings' | 'credit' | 'cash'
export type RuleField = 'payee' | 'memo'
export type GoalKind = 'savings_target' | 'spending_cap'

export interface Timestamps {
  created_at: string
  updated_at: string
}

// --- Account ---------------------------------------------------------------

export interface AccountBase {
  name: string
  kind: AccountKind
  opening_balance_cents: number
  archived: boolean
}

export type AccountCreate = AccountBase

export interface AccountUpdate {
  name?: string | null
  kind?: AccountKind | null
  opening_balance_cents?: number | null
  archived?: boolean | null
}

export interface AccountRead extends AccountBase, Timestamps {
  id: number
}

// --- CategoryGroup ---------------------------------------------------------

export interface CategoryGroupBase {
  name: string
  sort_order: number
}

export type CategoryGroupCreate = CategoryGroupBase

export interface CategoryGroupRead extends CategoryGroupBase, Timestamps {
  id: number
}

// --- Category --------------------------------------------------------------

export interface CategoryBase {
  group_id: number
  name: string
  sort_order: number
  archived: boolean
}

export type CategoryCreate = CategoryBase

export interface CategoryRead extends CategoryBase, Timestamps {
  id: number
}

// --- Transaction -----------------------------------------------------------

export interface TransactionBase {
  account_id: number
  category_id: number | null
  date: string
  payee: string
  amount_cents: number
  memo: string
  cleared: boolean
  import_hash: string | null
}

export type TransactionCreate = TransactionBase

export interface TransactionUpdate {
  account_id?: number | null
  category_id?: number | null
  date?: string | null
  payee?: string | null
  amount_cents?: number | null
  memo?: string | null
  cleared?: boolean | null
  import_hash?: string | null
}

export interface TransactionRead extends TransactionBase, Timestamps {
  id: number
}

// --- Allocation ------------------------------------------------------------

export interface AllocationBase {
  month: string
  category_id: number
  amount_cents: number
}

export type AllocationCreate = AllocationBase

export interface AllocationRead extends AllocationBase, Timestamps {
  id: number
}

// --- CategoryRule ----------------------------------------------------------

export interface CategoryRuleBase {
  match_field: RuleField
  pattern: string
  category_id: number
  priority: number
}

export type CategoryRuleCreate = CategoryRuleBase

export interface CategoryRuleRead extends CategoryRuleBase, Timestamps {
  id: number
}

// --- Goal ------------------------------------------------------------------

export interface GoalBase {
  category_id: number
  kind: GoalKind
  target_cents: number
  target_month: string | null
}

export type GoalCreate = GoalBase

export interface GoalRead extends GoalBase, Timestamps {
  id: number
}

// --- API responses / requests ----------------------------------------------

export interface HealthResponse {
  status: string
  time: string
}

export interface CategoryGroupWithCategories extends CategoryGroupBase, Timestamps {
  id: number
  categories: CategoryRead[]
}

export interface TransactionWithRelations extends TransactionRead {
  account: AccountRead
  category: CategoryRead | null
}

export interface TransactionListResponse {
  items: TransactionWithRelations[]
  next_cursor: string | null
}

export interface CountResponse {
  count: number
}

export interface PayeeSuggestion {
  payee: string
  suggested_category_id: number | null
  count: number
}

export interface BulkCategorizeRequest {
  ids: number[]
  category_id: number | null
}

export interface BulkCategorizeResponse {
  updated: number
}

export interface DeletedResponse {
  id: number
  deleted: boolean
}

export interface GroupReorderRequest {
  group_ids: number[]
}

export interface AllocationUpsertRequest {
  amount_cents: number
}

export interface CopyFromPreviousResponse {
  month: string
  source_month: string
  copied: number
}

// Budget month-view (mirror app/budget.py dataclasses).

export interface CategoryBudgetRow {
  id: number
  name: string
  assigned_cents: number
  activity_cents: number
  available_cents: number
}

export interface GroupBudget {
  id: number
  name: string
  categories: CategoryBudgetRow[]
  assigned_cents: number
  activity_cents: number
  available_cents: number
}

export interface MonthBudget {
  month: string
  groups: GroupBudget[]
  income_cents: number
  assigned_cents: number
  activity_cents: number
  available_cents: number
  left_to_assign_cents: number
}

// --- CSV import ------------------------------------------------------------

export type AmountShape = 'signed' | 'debit_credit' | 'amount_type'

export interface ImportMapping {
  amount_shape: AmountShape
  date_col: number | null
  payee_col: number | null
  memo_col: number | null
  amount_col: number | null
  debit_col: number | null
  credit_col: number | null
  type_col: number | null
}

export interface ImportPreviewRow {
  row_index: number
  date: string | null
  payee: string
  amount_cents: number | null
  memo: string
  proposed_category_id: number | null
  is_duplicate: boolean
  importable: boolean
  import_hash: string | null
  warnings: string[]
}

export interface ImportPreviewResponse {
  token: string
  account_id: number
  delimiter: string
  has_header: boolean
  columns: string[]
  mapping: ImportMapping
  raw_sample: string[][]
  rows: ImportPreviewRow[]
  warnings: string[]
}

export interface ImportCommitRow {
  date: string
  payee: string
  amount_cents: number
  memo: string
  category_id: number | null
  is_duplicate: boolean
}

export interface ImportCommitResponse {
  imported: number
  skipped_duplicate: number
  failed: number
}

export interface RuleApplyResponse {
  changed: number
}

// --- Bank sync -------------------------------------------------------------

export interface SyncAccountStatus {
  external_id: string
  name: string
  org_name: string
  currency: string
  reported_balance_cents: number | null
  balance_date: string | null
  linked_account_id: number | null
  local_account_name: string | null
  computed_balance_cents: number | null
  last_synced_at: string | null
  opening_balance_source: string | null
  mismatch: boolean
}

export interface SyncRunRead {
  id: number
  started_at: string
  finished_at: string | null
  status: 'ok' | 'partial' | 'failed'
  accounts_synced: number
  added: number
  updated: number
  errors: unknown[]
}

// --- Insights --------------------------------------------------------------

export interface CategorySpend {
  id: number
  name: string
  spent_cents: number
  compare_cents: number
}

export interface GroupSpend {
  id: number
  name: string
  spent_cents: number
  compare_cents: number
  categories: CategorySpend[]
}

export interface ByCategoryResponse {
  month: string
  compare_to: string
  total_spent_cents: number
  total_compare_cents: number
  groups: GroupSpend[]
}

export interface TrendPoint {
  month: string
  spent_cents: number
}

export interface TrendCategory {
  id: number
  name: string
  points: TrendPoint[]
  current_month: string
  mean_cents: number
  stddev_cents: number
  is_outlier: boolean
  reason: string | null
}

export interface TrendsResponse {
  months: string[]
  categories: TrendCategory[]
}

export interface BurnPoint {
  day: number
  cumulative_cents: number
}

export interface BurnSeries {
  month: string
  points: BurnPoint[]
}

export interface BurnResponse {
  month: string
  days_in_month: number
  as_of_day: number
  current: BurnPoint[]
  history: BurnSeries[]
  projected_total_cents: number | null
  assumption: string
}

export interface RecurringItem {
  payee: string
  category_id: number | null
  category_name: string | null
  average_amount_cents: number
  cadence_days: number
  occurrences: number
  last_date: string
  next_expected_date: string
  next_expected_amount_cents: number
}

export interface RecurringResponse {
  items: RecurringItem[]
  total_committed_monthly_cents: number
}

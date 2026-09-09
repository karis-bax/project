/**
 * API shapes, mirroring backend/app/schemas.py field for field.
 *
 * Money is always a signed integer number of cents. `date` is ISO YYYY-MM-DD,
 * `month` is YYYY-MM.
 */

export type AccountKind = 'checking' | 'savings' | 'credit' | 'cash'

export interface UserRead {
  id: number
  email: string
  is_active: boolean
  created_at: string
}

export interface TokenPairResponse {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
}

export interface AccountRead {
  id: number
  name: string
  kind: AccountKind
  opening_balance_cents: number
  archived: boolean
  created_at: string
  updated_at: string
}

export interface CategoryBudgetRow {
  id: number
  name: string
  assigned_cents: number
  activity_cents: number
  available_cents: number
  pending_cents: number
}

export interface GroupBudget {
  id: number
  name: string
  categories: CategoryBudgetRow[]
  assigned_cents: number
  activity_cents: number
  available_cents: number
  pending_cents: number
}

export interface MonthBudget {
  month: string
  groups: GroupBudget[]
  income_cents: number
  assigned_cents: number
  activity_cents: number
  available_cents: number
  left_to_assign_cents: number
  pending_cents: number
}

export interface TransactionCreate {
  account_id: number
  category_id: number | null
  date: string
  payee: string
  amount_cents: number
  memo: string
  cleared: boolean
  pending: boolean
  import_hash: string | null
}

export interface TransactionRead extends TransactionCreate {
  id: number
  created_at: string
  updated_at: string
}

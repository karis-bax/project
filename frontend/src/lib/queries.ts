/**
 * TanStack Query hooks for every backend endpoint.
 *
 * Query keys are structured for targeted invalidation:
 *   ['health']
 *   ['accounts', { includeArchived }]
 *   ['categories', { includeArchived }]
 *   ['transactions', filters]
 *   ['budget', month]
 */

import {
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'

import { api } from './api'
import type {
  AccountCreate,
  AccountRead,
  AccountUpdate,
  AllocationRead,
  BulkCategorizeRequest,
  BulkCategorizeResponse,
  CategoryCreate,
  CategoryGroupCreate,
  CategoryGroupRead,
  CategoryGroupWithCategories,
  CategoryRead,
  CategoryRuleCreate,
  CategoryRuleRead,
  CopyFromPreviousResponse,
  CountResponse,
  DeletedResponse,
  GoalRead,
  HealthResponse,
  ImportCommitResponse,
  ImportCommitRow,
  ImportMapping,
  ImportPreviewResponse,
  BurnResponse,
  ByCategoryResponse,
  MonthBudget,
  PayeeSuggestion,
  RecurringResponse,
  RuleApplyResponse,
  SyncAccountStatus,
  SyncRunRead,
  TrendsResponse,
  TransactionCreate,
  TransactionListResponse,
  TransactionRead,
  TransactionUpdate,
} from './types'

export interface TransactionFilters {
  month?: string
  account_id?: number
  category_id?: number
  q?: string
  uncategorized?: boolean
  limit?: number
}

export const queryKeys = {
  health: ['health'] as const,
  accounts: (includeArchived = false) =>
    ['accounts', { includeArchived }] as const,
  categories: (includeArchived = false) =>
    ['categories', { includeArchived }] as const,
  transactions: (filters: TransactionFilters) =>
    ['transactions', filters] as const,
  transactionsCount: (filters: TransactionFilters) =>
    ['transactions', 'count', filters] as const,
  payees: ['payees'] as const,
  budget: (month: string) => ['budget', month] as const,
  goals: ['goals'] as const,
  rules: ['rules'] as const,
  syncAccounts: ['sync', 'accounts'] as const,
  syncRuns: ['sync', 'runs'] as const,
  insightsByCategory: (month: string, compareTo?: string) =>
    ['insights', 'by-category', month, compareTo ?? null] as const,
  insightsTrends: (months: number) => ['insights', 'trends', months] as const,
  insightsBurn: (month: string) => ['insights', 'burn', month] as const,
  insightsRecurring: ['insights', 'recurring'] as const,
}

/**
 * Invalidate every query root that reads transaction data. Call this from ANY
 * mutation that can change transactions (create/update/delete/bulk/import/sync/
 * rules-apply). When you add a new screen or query that derives from
 * transaction data, add its root HERE — do not re-list keys per hook, or the
 * set will drift and screens will show stale data.
 */
export function invalidateAfterTransactionChange(qc: QueryClient): void {
  qc.invalidateQueries({ queryKey: ['transactions'] })
  qc.invalidateQueries({ queryKey: ['budget'] })
  qc.invalidateQueries({ queryKey: ['insights'] })
  qc.invalidateQueries({ queryKey: queryKeys.syncAccounts })
  qc.invalidateQueries({ queryKey: queryKeys.payees })
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') {
      search.set(key, String(value))
    }
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

// --- Queries ---------------------------------------------------------------

export function useHealth() {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: () => api.get<HealthResponse>('/health'),
  })
}

export function useAccounts(includeArchived = false) {
  return useQuery({
    queryKey: queryKeys.accounts(includeArchived),
    queryFn: () =>
      api.get<AccountRead[]>(
        `/accounts${buildQuery({ include_archived: includeArchived })}`,
      ),
  })
}

export function useCategories(includeArchived = false) {
  return useQuery({
    queryKey: queryKeys.categories(includeArchived),
    queryFn: () =>
      api.get<CategoryGroupWithCategories[]>(
        `/categories${buildQuery({ include_archived: includeArchived })}`,
      ),
  })
}

export function useTransactions(filters: TransactionFilters = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.transactions(filters),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      api.get<TransactionListResponse>(
        `/transactions${buildQuery({ ...filters, cursor: pageParam })}`,
      ),
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
  })
}

export function useBudget(month: string) {
  return useQuery({
    queryKey: queryKeys.budget(month),
    queryFn: () => api.get<MonthBudget>(`/budget/${month}`),
    enabled: Boolean(month),
  })
}

export function useGoals() {
  return useQuery({
    queryKey: queryKeys.goals,
    queryFn: () => api.get<GoalRead[]>('/goals'),
  })
}

export function useTransactionsCount(filters: TransactionFilters = {}) {
  return useQuery({
    queryKey: queryKeys.transactionsCount(filters),
    queryFn: () =>
      api.get<CountResponse>(`/transactions/count${buildQuery({ ...filters })}`),
  })
}

export function usePayees() {
  return useQuery({
    queryKey: queryKeys.payees,
    queryFn: () => api.get<PayeeSuggestion[]>('/transactions/payees'),
  })
}

// --- Account mutations -----------------------------------------------------

export function useCreateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: AccountCreate) => api.post<AccountRead>('/accounts', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['accounts'] }),
  })
}

export function useUpdateAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: AccountUpdate }) =>
      api.patch<AccountRead>(`/accounts/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['accounts'] }),
  })
}

export function useArchiveAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del<AccountRead>(`/accounts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['accounts'] }),
  })
}

// --- Category / group mutations --------------------------------------------

export function useCreateCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CategoryCreate) =>
      api.post<CategoryRead>('/categories', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['categories'] }),
  })
}

export function useUpdateCategory() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<CategoryCreate> }) =>
      api.patch<CategoryRead>(`/categories/${id}`, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['categories'] }),
  })
}

export function useDeleteCategory() {
  const qc = useQueryClient()
  return useMutation({
    // Archiving returns the archive-month + future allocations. If the category
    // still holds an available balance, pass absorbTo (move it) or discard.
    mutationFn: ({
      id,
      absorbTo,
      discard,
    }: {
      id: number
      absorbTo?: number
      discard?: boolean
    }) =>
      api.del<CategoryRead>(
        `/categories/${id}${buildQuery({ absorb_to: absorbTo, discard })}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['categories'] })
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['budget'] })
    },
  })
}

export function useCreateCategoryGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CategoryGroupCreate) =>
      api.post<CategoryGroupRead>('/category-groups', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['categories'] }),
  })
}

export function useReorderCategoryGroups() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (groupIds: number[]) =>
      api.patch<CategoryGroupRead[]>('/category-groups/reorder', {
        group_ids: groupIds,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['categories'] }),
  })
}

// --- Transaction mutations -------------------------------------------------

export function useCreateTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: TransactionCreate) =>
      api.post<TransactionRead>('/transactions', body),
    onSuccess: () => invalidateAfterTransactionChange(qc),
  })
}

export function useUpdateTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: TransactionUpdate }) =>
      api.patch<TransactionRead>(`/transactions/${id}`, body),
    onSuccess: () => invalidateAfterTransactionChange(qc),
  })
}

export function useDeleteTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del<DeletedResponse>(`/transactions/${id}`),
    onSuccess: () => invalidateAfterTransactionChange(qc),
  })
}

export function useBulkCategorize() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BulkCategorizeRequest) =>
      api.post<BulkCategorizeResponse>('/transactions/bulk-categorize', body),
    onSuccess: () => invalidateAfterTransactionChange(qc),
  })
}

export function useMarkTransactionsCleared() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ ids, cleared }: { ids: number[]; cleared: boolean }) => {
      await Promise.all(
        ids.map((id) =>
          api.patch<TransactionRead>(`/transactions/${id}`, { cleared }),
        ),
      )
    },
    onSuccess: () => invalidateAfterTransactionChange(qc),
  })
}

// --- Budget mutations ------------------------------------------------------

export function useUpsertAllocation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      month,
      categoryId,
      amountCents,
    }: {
      month: string
      categoryId: number
      amountCents: number
    }) =>
      api.put<AllocationRead>(
        `/budget/${month}/allocations/${categoryId}`,
        { amount_cents: amountCents },
      ),
    onSuccess: (_data, variables) =>
      qc.invalidateQueries({ queryKey: queryKeys.budget(variables.month) }),
  })
}

export function useCopyFromPrevious() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (month: string) =>
      api.post<CopyFromPreviousResponse>(`/budget/${month}/copy-from-previous`),
    onSuccess: (_data, month) =>
      qc.invalidateQueries({ queryKey: queryKeys.budget(month) }),
  })
}

// --- CSV import ------------------------------------------------------------

export function useImportPreview() {
  return useMutation({
    mutationFn: ({ file, accountId }: { file: File; accountId: number }) => {
      const form = new FormData()
      form.append('account_id', String(accountId))
      form.append('file', file)
      return api.postForm<ImportPreviewResponse>('/import/preview', form)
    },
  })
}

export function useImportRemap() {
  return useMutation({
    mutationFn: ({ token, mapping }: { token: string; mapping: ImportMapping }) =>
      api.post<ImportPreviewResponse>('/import/remap', { token, mapping }),
  })
}

export function useImportCommit() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      token,
      rows,
      skipDuplicates,
    }: {
      token: string
      rows: ImportCommitRow[]
      skipDuplicates: boolean
    }) =>
      api.post<ImportCommitResponse>('/import/commit', {
        token,
        rows,
        skip_duplicates: skipDuplicates,
      }),
    onSuccess: () => invalidateAfterTransactionChange(qc),
  })
}

// --- Rules -----------------------------------------------------------------

export function useRules() {
  return useQuery({
    queryKey: queryKeys.rules,
    queryFn: () => api.get<CategoryRuleRead[]>('/rules'),
  })
}

export function useCreateRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CategoryRuleCreate) =>
      api.post<CategoryRuleRead>('/rules', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.rules }),
  })
}

export function useDeleteRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del<DeletedResponse>(`/rules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.rules }),
  })
}

export function useReorderRules() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (ruleIds: number[]) =>
      api.patch<CategoryRuleRead[]>('/rules/reorder', { rule_ids: ruleIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.rules }),
  })
}

export function useApplyRules() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (month?: string) =>
      api.post<RuleApplyResponse>(
        `/rules/apply${month ? `?month=${month}` : ''}`,
      ),
    onSuccess: () => invalidateAfterTransactionChange(qc),
  })
}

// --- Bank sync -------------------------------------------------------------

export function useSyncAccounts() {
  return useQuery({
    queryKey: queryKeys.syncAccounts,
    queryFn: () => api.get<SyncAccountStatus[]>('/sync/accounts'),
  })
}

export function useSyncRuns() {
  return useQuery({
    queryKey: queryKeys.syncRuns,
    queryFn: () => api.get<SyncRunRead[]>('/sync/runs'),
  })
}

export function useClaimSetupToken() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (setupToken: string) =>
      api.post<SyncAccountStatus[]>('/sync/claim', { setup_token: setupToken }),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.syncAccounts }),
  })
}

export function useLinkSyncAccount() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: {
      external_id: string
      account_id?: number
      create_as?: { name: string; kind: string }
    }) => api.post<SyncAccountStatus[]>('/sync/link', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.syncAccounts })
      qc.invalidateQueries({ queryKey: ['accounts'] })
    },
  })
}

export function useRunSync() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (days: number = 30) =>
      api.post<SyncRunRead>('/sync/run', { days }),
    onSuccess: () => {
      invalidateAfterTransactionChange(qc)
      qc.invalidateQueries({ queryKey: queryKeys.syncRuns })
    },
  })
}

// --- Insights --------------------------------------------------------------

export function useInsightsByCategory(month: string, compareTo?: string) {
  return useQuery({
    queryKey: queryKeys.insightsByCategory(month, compareTo),
    queryFn: () =>
      api.get<ByCategoryResponse>(
        `/insights/by-category${buildQuery({ month, compare_to: compareTo })}`,
      ),
    enabled: Boolean(month),
  })
}

export function useInsightsTrends(months = 6) {
  return useQuery({
    queryKey: queryKeys.insightsTrends(months),
    queryFn: () =>
      api.get<TrendsResponse>(`/insights/trends${buildQuery({ months })}`),
  })
}

export function useInsightsBurn(month: string) {
  return useQuery({
    queryKey: queryKeys.insightsBurn(month),
    queryFn: () => api.get<BurnResponse>(`/insights/burn${buildQuery({ month })}`),
    enabled: Boolean(month),
  })
}

export function useInsightsRecurring() {
  return useQuery({
    queryKey: queryKeys.insightsRecurring,
    queryFn: () => api.get<RecurringResponse>('/insights/recurring'),
  })
}

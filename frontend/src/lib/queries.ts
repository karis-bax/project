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
  CopyFromPreviousResponse,
  DeletedResponse,
  GoalRead,
  HealthResponse,
  MonthBudget,
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
  budget: (month: string) => ['budget', month] as const,
  goals: ['goals'] as const,
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
    mutationFn: ({ id, reassignTo }: { id: number; reassignTo?: number }) =>
      api.del<CategoryRead>(
        `/categories/${id}${buildQuery({ reassign_to: reassignTo })}`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['categories'] })
      qc.invalidateQueries({ queryKey: ['transactions'] })
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['budget'] })
    },
  })
}

export function useUpdateTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: TransactionUpdate }) =>
      api.patch<TransactionRead>(`/transactions/${id}`, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['budget'] })
    },
  })
}

export function useDeleteTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del<DeletedResponse>(`/transactions/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['budget'] })
    },
  })
}

export function useBulkCategorize() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: BulkCategorizeRequest) =>
      api.post<BulkCategorizeResponse>('/transactions/bulk-categorize', body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['transactions'] })
      qc.invalidateQueries({ queryKey: ['budget'] })
    },
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

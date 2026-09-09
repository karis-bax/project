/** TanStack Query hooks. Query keys mirror the web client's shape. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'
import type { AccountRead, MonthBudget, TransactionCreate, TransactionRead } from './types'

export function currentMonth(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export function today(): string {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(
    now.getDate(),
  ).padStart(2, '0')}`
}

export function useBudget(month: string) {
  return useQuery({
    queryKey: ['budget', month],
    queryFn: () => api.get<MonthBudget>(`/api/budget/${month}`),
  })
}

export function useAccounts() {
  return useQuery({
    queryKey: ['accounts'],
    queryFn: () => api.get<AccountRead[]>('/api/accounts'),
  })
}

/**
 * Anything that changes transaction data invalidates every root that reads it.
 * Same discipline as the web client's invalidateAfterTransactionChange — a new
 * query root that reads transactions gets added here too.
 */
function invalidateTransactionReaders(qc: ReturnType<typeof useQueryClient>): void {
  void qc.invalidateQueries({ queryKey: ['budget'] })
  void qc.invalidateQueries({ queryKey: ['transactions'] })
  void qc.invalidateQueries({ queryKey: ['insights'] })
  void qc.invalidateQueries({ queryKey: ['accounts'] })
}

export function useCreateTransaction() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: TransactionCreate) =>
      api.post<TransactionRead>('/api/transactions', payload),
    onSuccess: () => invalidateTransactionReaders(qc),
  })
}

import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../lib/api'
import {
  useTransactions,
  usePayees,
  type TransactionFilters,
} from '../lib/queries'
import { EmptyState, ErrorState, SkeletonRows } from '../components/ui'
import { FilterBar } from '../components/transactions/FilterBar'
import { Register, type ActivateModifiers } from '../components/transactions/Register'
import { SelectionBar } from '../components/transactions/SelectionBar'

function readFilters(params: URLSearchParams): TransactionFilters {
  const filters: TransactionFilters = {}
  const month = params.get('month')
  const accountId = params.get('account_id')
  const categoryId = params.get('category_id')
  const q = params.get('q')
  if (month) filters.month = month
  if (accountId) filters.account_id = Number(accountId)
  if (categoryId) filters.category_id = Number(categoryId)
  if (q) filters.q = q
  if (params.get('uncategorized') === 'true') filters.uncategorized = true
  return filters
}

function writeFilters(filters: TransactionFilters): URLSearchParams {
  const params = new URLSearchParams()
  if (filters.month) params.set('month', filters.month)
  if (filters.account_id) params.set('account_id', String(filters.account_id))
  if (filters.category_id) params.set('category_id', String(filters.category_id))
  if (filters.q) params.set('q', filters.q)
  if (filters.uncategorized) params.set('uncategorized', 'true')
  return params
}

export function TransactionsPage() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => readFilters(params), [params])
  const hasActiveFilters = Object.keys(filters).length > 0

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [anchorIndex, setAnchorIndex] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)

  const query = useTransactions({ ...filters, limit: 100 })
  const payees = usePayees()

  const items = useMemo(
    () => query.data?.pages.flatMap((page) => page.items) ?? [],
    [query.data],
  )

  const setFilters = (next: TransactionFilters) => {
    setSelectedIds(new Set())
    setEditingId(null)
    setParams(writeFilters(next))
  }

  const clearFilters = () => setFilters({})

  const onActivate = (id: number, index: number, mods: ActivateModifiers) => {
    if (mods.shift && anchorIndex !== null) {
      const [lo, hi] = [anchorIndex, index].sort((a, b) => a - b)
      setSelectedIds(new Set(items.slice(lo, hi + 1).map((t) => t.id)))
      return
    }
    if (mods.meta) {
      setSelectedIds((prev) => {
        const next = new Set(prev)
        if (next.has(id)) next.delete(id)
        else next.add(id)
        return next
      })
      setAnchorIndex(index)
      return
    }
    // Plain click opens the inline edit row (and clears any selection).
    setSelectedIds(new Set())
    setAnchorIndex(index)
    setEditingId((prev) => (prev === id ? null : id))
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-3">
      <FilterBar filters={filters} onChange={setFilters} />

      {selectedIds.size > 0 && (
        <SelectionBar
          selectedIds={[...selectedIds]}
          onClear={() => setSelectedIds(new Set())}
        />
      )}

      {query.isLoading ? (
        <SkeletonRows rows={12} />
      ) : query.isError ? (
        <ErrorState
          message={
            query.error instanceof ApiError
              ? query.error.detail
              : 'Failed to load transactions.'
          }
        />
      ) : (
        <Register
          items={items}
          payees={payees.data ?? []}
          hasNextPage={Boolean(query.hasNextPage)}
          isFetchingNextPage={query.isFetchingNextPage}
          fetchNextPage={query.fetchNextPage}
          selectedIds={selectedIds}
          editingId={editingId}
          onActivate={onActivate}
          onCloseEdit={() => setEditingId(null)}
          emptyState={
            <EmptyState
              title="No transactions match"
              hint={
                hasActiveFilters
                  ? 'No transactions match the current filters.'
                  : 'Add your first transaction with the quick-add row above.'
              }
              action={
                hasActiveFilters ? (
                  <button
                    type="button"
                    onClick={clearFilters}
                    className="mt-1 rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--accent)] hover:bg-[var(--row-hover)]"
                  >
                    Clear filters
                  </button>
                ) : undefined
              }
            />
          }
        />
      )}
    </div>
  )
}

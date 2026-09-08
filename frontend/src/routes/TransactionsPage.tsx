import { useSearchParams } from 'react-router-dom'

import { ApiError } from '../lib/api'
import { useTransactions, type TransactionFilters } from '../lib/queries'
import { EmptyState, ErrorState, Placeholder, SkeletonRows } from '../components/ui'

export function TransactionsPage() {
  const [params] = useSearchParams()

  const filters: TransactionFilters = { limit: 50 }
  const month = params.get('month')
  const categoryId = params.get('category_id')
  const uncategorized = params.get('uncategorized')
  const q = params.get('q')
  if (month) filters.month = month
  if (categoryId) filters.category_id = Number(categoryId)
  if (uncategorized === 'true') filters.uncategorized = true
  if (q) filters.q = q

  const { data, isLoading, isError, error } = useTransactions(filters)

  if (isLoading) {
    return (
      <div className="max-w-4xl">
        <SkeletonRows rows={10} />
      </div>
    )
  }
  if (isError) {
    const message =
      error instanceof ApiError ? error.detail : 'Failed to load transactions.'
    return <ErrorState message={message} />
  }

  const items = data?.pages.flatMap((page) => page.items) ?? []
  if (items.length === 0) {
    return (
      <EmptyState
        title="No transactions match"
        hint="Try clearing filters, or add transactions to get started."
      />
    )
  }

  const activeFilters = [
    filters.month && `month ${filters.month}`,
    filters.category_id && `category #${filters.category_id}`,
    filters.uncategorized && 'uncategorized',
    filters.q && `“${filters.q}”`,
  ].filter(Boolean)

  return (
    <div className="max-w-4xl">
      <Placeholder
        title="Transactions table arrives in the next phase"
        hint={`${items.length} transaction(s) loaded from the live API${
          activeFilters.length ? ` · filtered by ${activeFilters.join(', ')}` : ''
        }.`}
      />
    </div>
  )
}

import { useTransactions } from '../lib/queries'
import { ApiError } from '../lib/api'
import { EmptyState, ErrorState, Placeholder, SkeletonRows } from '../components/ui'

export function TransactionsPage() {
  const { data, isLoading, isError, error } = useTransactions({ limit: 50 })

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
        title="No transactions yet"
        hint="Imported and manually added transactions will show up here."
      />
    )
  }

  return (
    <div className="max-w-4xl">
      <Placeholder
        title="Transactions table arrives in the next phase"
        hint={`${items.length} transaction(s) loaded from the live API.`}
      />
    </div>
  )
}

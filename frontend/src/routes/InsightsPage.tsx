import { currentMonth } from '../lib/month'
import { useBudget } from '../lib/queries'
import { ApiError } from '../lib/api'
import { EmptyState, ErrorState, Placeholder, SkeletonRows } from '../components/ui'

export function InsightsPage() {
  // Insights are derived from budget data; load the current month as a source.
  const month = currentMonth()
  const { data, isLoading, isError, error } = useBudget(month)

  if (isLoading) {
    return (
      <div className="max-w-3xl">
        <SkeletonRows rows={6} />
      </div>
    )
  }
  if (isError) {
    const message = error instanceof ApiError ? error.detail : 'Failed to load insights.'
    return <ErrorState message={message} />
  }
  if (!data || data.groups.length === 0) {
    return (
      <EmptyState
        title="No insights yet"
        hint="Once you have budgeted months and spending, trends will appear here."
      />
    )
  }

  return (
    <div className="max-w-3xl">
      <Placeholder
        title="Insights & charts arrive in a later phase"
        hint="Spending trends, category breakdowns, and net worth over time."
      />
    </div>
  )
}

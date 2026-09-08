import { useParams } from 'react-router-dom'

import { ApiError } from '../lib/api'
import { isValidMonth } from '../lib/month'
import { useBudget, useCopyFromPrevious, useGoals } from '../lib/queries'
import { BudgetToolbar } from '../components/budget/BudgetToolbar'
import { EnvelopeGrid } from '../components/budget/EnvelopeGrid'
import { LeftToAssignBanner } from '../components/budget/LeftToAssignBanner'
import { EmptyState, ErrorState, Skeleton, SkeletonRows } from '../components/ui'

export function BudgetPage() {
  const { month = '' } = useParams()
  const valid = isValidMonth(month)
  const budget = useBudget(valid ? month : '')
  const goals = useGoals()
  const copy = useCopyFromPrevious()

  if (!valid) {
    return (
      <ErrorState message={`"${month}" is not a valid month (expected YYYY-MM).`} />
    )
  }

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <BudgetToolbar
        month={month}
        copying={copy.isPending}
        onCopyFromLast={() => copy.mutate(month)}
      />

      {budget.isLoading ? (
        <>
          <Skeleton height={64} className="rounded-md" />
          <SkeletonRows rows={10} />
        </>
      ) : budget.isError ? (
        <ErrorState
          message={
            budget.error instanceof ApiError
              ? budget.error.detail
              : 'Failed to load the budget.'
          }
        />
      ) : !budget.data || budget.data.groups.length === 0 ? (
        <EmptyState
          title="Nothing budgeted yet"
          hint="Create a category group and give every dollar a job to get started."
        />
      ) : (
        <>
          <LeftToAssignBanner cents={budget.data.left_to_assign_cents} />
          <EnvelopeGrid
            month={month}
            data={budget.data}
            goals={goals.data ?? []}
          />
        </>
      )}
    </div>
  )
}

import { useParams } from 'react-router-dom'

import { isValidMonth } from '../lib/month'
import { useBudget } from '../lib/queries'
import { ApiError } from '../lib/api'
import { EmptyState, ErrorState, Money, Placeholder, SkeletonRows } from '../components/ui'

function Stat({ label, cents, sign = false }: { label: string; cents: number; sign?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
        {label}
      </span>
      <Money cents={cents} sign={sign} className="text-[15px]" />
    </div>
  )
}

export function BudgetPage() {
  const { month = '' } = useParams()
  const valid = isValidMonth(month)
  const { data, isLoading, isError, error } = useBudget(valid ? month : '')

  if (!valid) {
    return <ErrorState message={`"${month}" is not a valid month (expected YYYY-MM).`} />
  }
  if (isLoading) {
    return (
      <div className="max-w-3xl">
        <SkeletonRows rows={8} />
      </div>
    )
  }
  if (isError) {
    const message = error instanceof ApiError ? error.detail : 'Failed to load the budget.'
    return <ErrorState message={message} />
  }
  if (!data || data.groups.length === 0) {
    return (
      <EmptyState
        title="Nothing budgeted yet"
        hint="Create a category group and give every dollar a job to get started."
      />
    )
  }

  const categoryCount = data.groups.reduce((n, g) => n + g.categories.length, 0)

  return (
    <div className="flex max-w-3xl flex-col gap-5">
      <section className="flex flex-wrap items-end gap-8 border-b border-[var(--border)] pb-4">
        <Stat label="Left to assign" cents={data.left_to_assign_cents} sign />
        <Stat label="Income" cents={data.income_cents} />
        <Stat label="Assigned" cents={data.assigned_cents} />
        <Stat label="Activity" cents={data.activity_cents} />
      </section>
      <Placeholder
        title="Budget ledger arrives in the next phase"
        hint={`${data.groups.length} groups · ${categoryCount} categories connected from the live API.`}
      />
    </div>
  )
}

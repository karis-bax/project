import { formatCents } from '../../lib/money'
import { useInsightsRecurring } from '../../lib/queries'
import { EmptyState, Money, SkeletonRows } from '../ui'

export function RecurringView() {
  const { data, isLoading } = useInsightsRecurring()

  if (isLoading) return <SkeletonRows rows={6} />
  if (!data || data.items.length === 0) {
    return (
      <EmptyState
        title="No recurring charges detected"
        hint="Recurring detection needs a few months of monthly, similar-amount charges."
      />
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between rounded-md border border-[var(--border)] bg-[var(--panel)] px-3 py-2">
        <span className="text-[var(--fg-muted)]">Total committed monthly</span>
        <span className="num text-lg font-semibold tabular-nums text-[var(--fg)]">
          {formatCents(data.total_committed_monthly_cents)}
        </span>
      </div>

      <div className="rounded-md border border-[var(--border)]">
        <div
          className="grid gap-2 border-b border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]"
          style={{ gridTemplateColumns: '1.4fr 1fr 8rem 8rem 5rem' }}
        >
          <span>Payee</span>
          <span>Category</span>
          <span>Next expected</span>
          <span className="text-right">Amount</span>
          <span className="text-right">Every</span>
        </div>
        {data.items.map((item) => (
          <div
            key={item.payee}
            className="grid items-center gap-2 border-b border-[var(--border)] px-3 py-1.5 last:border-b-0"
            style={{ gridTemplateColumns: '1.4fr 1fr 8rem 8rem 5rem' }}
          >
            <span className="truncate text-[var(--fg)]">{item.payee}</span>
            <span className="truncate text-[var(--fg-muted)]">
              {item.category_name ?? (
                <span className="italic text-[var(--fg-subtle)]">Uncategorized</span>
              )}
            </span>
            <span className="num tabular-nums text-[var(--fg-muted)]">
              {item.next_expected_date}
            </span>
            <span className="text-right">
              <Money cents={item.average_amount_cents} />
            </span>
            <span className="num text-right tabular-nums text-[var(--fg-subtle)]">
              {item.cadence_days}d
            </span>
          </div>
        ))}
      </div>
      <p className="text-[var(--fg-muted)]">
        Charges that repeat monthly (within a few days and 10% on amount), with
        the next expected date and amount for each.
      </p>
    </div>
  )
}

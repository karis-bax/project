import { Link } from 'react-router-dom'

import { formatCents } from '../../lib/money'
import type { CategoryBudgetRow, GoalRead } from '../../lib/types'

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value))
}

/**
 * The Available column cell.
 *
 * Available is the decision number (full size, colour logic). Pending is
 * context: a smaller, muted secondary line that is NEVER folded into available
 * (the backend keeps them separate). Three states: no pending, pending but
 * still covered, and pending that would overspend the category once it settles.
 */
export function AvailableCell({
  category,
  goal,
  month,
}: {
  category: CategoryBudgetRow
  goal: GoalRead | undefined
  month: string
}) {
  const available = category.available_cents
  const pending = category.pending_cents // signed: outflow < 0, inflow > 0

  const availableColor =
    available < 0
      ? 'text-[var(--warn)]'
      : available === 0
        ? 'text-[var(--fg-subtle)]'
        : 'text-[var(--fg)]'

  // Optional goal progress meter (unchanged behaviour).
  let fill: number | null = null
  let meterClass = 'bg-[var(--accent-weak)]'
  if (goal && goal.target_cents > 0) {
    if (goal.kind === 'savings_target') {
      fill = clamp01(available / goal.target_cents)
    } else {
      const spent = -category.activity_cents
      fill = clamp01(spent / goal.target_cents)
      meterClass =
        spent > goal.target_cents ? 'bg-[var(--warn-weak)]' : 'bg-[var(--calm-weak)]'
    }
  }

  // Pending analysis. Outflows shrink available once they settle.
  const magnitude = Math.abs(pending)
  const projected = available + pending
  const short = pending !== 0 && available > 0 && projected < 0
  const shortfall = short ? -projected : 0

  // Visible pending text: outflow "$43 pending"; inflow "+$500 pending".
  let pendingText = ''
  if (pending !== 0) {
    pendingText =
      pending > 0
        ? `+${formatCents(magnitude)} pending`
        : `${formatCents(magnitude)} pending`
    if (short) pendingText += ` · ${formatCents(shortfall)} short`
  }

  // One coherent screen-reader sentence (avoids "127 43").
  let sentence = `Available ${formatCents(available)}`
  if (pending !== 0) {
    sentence +=
      pending > 0
        ? `, ${formatCents(magnitude)} pending inflow`
        : `, ${formatCents(magnitude)} pending`
    if (short) sentence += `, ${formatCents(shortfall)} short once pending clears`
  }

  return (
    <div className="relative flex flex-col items-end px-2 py-1">
      {fill !== null && (
        <div
          aria-hidden
          className={`absolute inset-y-1 left-1 rounded-sm ${meterClass}`}
          style={{ width: `calc(${fill * 100}% - 0.5rem)` }}
        />
      )}
      <span aria-hidden className={`num relative tabular-nums ${availableColor}`}>
        {formatCents(available)}
      </span>

      {/* Reserved second line: always present so the row height never jitters
          when a sync makes pending appear or disappear. */}
      <span
        data-testid="pending-slot"
        aria-hidden={pending === 0}
        className="relative block h-4 leading-4"
      >
        {pending !== 0 && (
          <Link
            to={`/transactions?category_id=${category.id}&month=${month}&pending=true`}
            aria-label={`Show pending transactions for ${category.name}`}
            title="Pending authorizations are not deducted from available."
            className={`num rounded text-[11px] tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent)] ${
              short ? 'text-[var(--warn)]' : 'text-[var(--fg-subtle)]'
            }`}
          >
            {pendingText}
          </Link>
        )}
      </span>

      <span className="sr-only">{sentence}</span>
    </div>
  )
}

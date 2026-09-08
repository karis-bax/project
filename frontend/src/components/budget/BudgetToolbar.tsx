import { useNavigate } from 'react-router-dom'

import { addMonths, currentMonth, formatMonthLabel } from '../../lib/month'

export function BudgetToolbar({
  month,
  onCopyFromLast,
  copying,
}: {
  month: string
  onCopyFromLast: () => void
  copying: boolean
}) {
  const navigate = useNavigate()
  const isCurrent = month === currentMonth()

  const stepBtn =
    'rounded px-2 py-1 text-[var(--fg-muted)] hover:bg-[var(--row-hover)] hover:text-[var(--fg)]'

  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="Previous month"
          className={stepBtn}
          onClick={() => navigate(`/budget/${addMonths(month, -1)}`)}
        >
          ‹
        </button>
        <span className="w-40 text-center font-medium text-[var(--fg)]">
          {formatMonthLabel(month)}
        </span>
        <button
          type="button"
          aria-label="Next month"
          className={stepBtn}
          onClick={() => navigate(`/budget/${addMonths(month, 1)}`)}
        >
          ›
        </button>
        <button
          type="button"
          disabled={isCurrent}
          className={`${stepBtn} ml-1 disabled:opacity-40`}
          onClick={() => navigate(`/budget/${currentMonth()}`)}
        >
          Today
        </button>
      </div>

      <button
        type="button"
        onClick={onCopyFromLast}
        disabled={copying}
        className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--fg)] hover:bg-[var(--row-hover)] disabled:opacity-50"
      >
        {copying ? 'Copying…' : 'Copy from last month'}
      </button>
    </div>
  )
}

import { useState } from 'react'

import { addMonths, currentMonth, formatMonthLabel } from '../lib/month'
import { ByCategoryView } from '../components/insights/ByCategoryView'
import { TrendsView } from '../components/insights/TrendsView'
import { BurnView } from '../components/insights/BurnView'
import { RecurringView } from '../components/insights/RecurringView'

type View = 'by-category' | 'trends' | 'burn' | 'recurring'

const TABS: { id: View; label: string; question: string }[] = [
  { id: 'by-category', label: 'Where did it go', question: 'Spending by category group' },
  { id: 'trends', label: 'Is this month unusual', question: 'Each category vs its own history' },
  { id: 'burn', label: 'When does it run out', question: 'Cumulative spend vs prior months' },
  { id: 'recurring', label: 'Recurring', question: 'Monthly committed charges' },
]

function MonthStepper({
  month,
  onChange,
}: {
  month: string
  onChange: (month: string) => void
}) {
  const btn =
    'rounded px-2 py-1 text-[var(--fg-muted)] hover:bg-[var(--row-hover)] hover:text-[var(--fg)]'
  return (
    <div className="flex items-center gap-1">
      <button type="button" className={btn} onClick={() => onChange(addMonths(month, -1))}>
        ‹
      </button>
      <span className="w-36 text-center font-medium text-[var(--fg)]">
        {formatMonthLabel(month)}
      </span>
      <button type="button" className={btn} onClick={() => onChange(addMonths(month, 1))}>
        ›
      </button>
    </div>
  )
}

export function InsightsPage() {
  const [view, setView] = useState<View>('by-category')
  const [month, setMonth] = useState<string>(currentMonth())

  const showStepper = view === 'by-category' || view === 'burn'
  const active = TABS.find((t) => t.id === view)!

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-[var(--fg)]">Insights</h1>
          <p className="text-[var(--fg-muted)]">{active.question}.</p>
        </div>
        {showStepper && <MonthStepper month={month} onChange={setMonth} />}
      </div>

      <div className="flex flex-wrap gap-1 border-b border-[var(--border)]">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setView(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-[13px] ${
              view === t.id
                ? 'border-[var(--accent)] font-medium text-[var(--accent)]'
                : 'border-transparent text-[var(--fg-muted)] hover:text-[var(--fg)]'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {view === 'by-category' && <ByCategoryView month={month} />}
      {view === 'trends' && <TrendsView />}
      {view === 'burn' && <BurnView month={month} />}
      {view === 'recurring' && <RecurringView />}
    </div>
  )
}

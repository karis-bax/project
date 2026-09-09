import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatCents } from '../../lib/money'
import { formatMonthLabel } from '../../lib/month'
import { useInsightsTrends } from '../../lib/queries'
import type { TrendCategory } from '../../lib/types'
import { EmptyState, SkeletonRows } from '../ui'
import { useChartTheme } from './useChartTheme'

function Sparkline({
  category,
  theme,
}: {
  category: TrendCategory
  theme: ReturnType<typeof useChartTheme>
}) {
  const data = category.points.map((p, i) => ({
    month: p.month,
    spent: p.spent_cents,
    isCurrent: i === category.points.length - 1,
  }))
  const stroke = category.is_outlier ? theme.warn : theme.accent

  return (
    <div className="rounded-md border border-[var(--border)] p-3">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="truncate font-medium text-[var(--fg)]">{category.name}</span>
        <span className="num tabular-nums text-[var(--fg-muted)]">
          {formatCents(category.points[category.points.length - 1].spent_cents)}
        </span>
      </div>
      <ResponsiveContainer width="100%" height={60}>
        <LineChart data={data} margin={{ top: 6, right: 6, bottom: 0, left: 6 }}>
          <XAxis dataKey="month" hide />
          <YAxis hide domain={[0, 'dataMax']} />
          <Tooltip
            contentStyle={{
              background: theme.panel,
              border: `1px solid ${theme.grid}`,
              color: theme.fg,
              fontSize: 12,
            }}
            labelFormatter={(m: string) => formatMonthLabel(m)}
            formatter={(v: number) => [formatCents(v), 'Spent']}
          />
          <Line
            type="monotone"
            dataKey="spent"
            stroke={stroke}
            strokeWidth={1.5}
            dot={(props: { cx?: number; cy?: number; payload?: { isCurrent?: boolean } }) => {
              const { cx, cy, payload } = props
              if (cx == null || cy == null || !payload?.isCurrent) {
                return <g key={`${cx}-${cy}`} />
              }
              return (
                <circle key={`${cx}-${cy}`} cx={cx} cy={cy} r={3.5} fill={stroke} />
              )
            }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      {category.is_outlier && category.reason ? (
        <p className="mt-1 text-[12px] text-[var(--warn)]">{category.reason}</p>
      ) : (
        <p className="mt-1 text-[12px] text-[var(--fg-subtle)]">
          Within its normal range.
        </p>
      )}
    </div>
  )
}

export function TrendsView() {
  const theme = useChartTheme()
  const { data, isLoading } = useInsightsTrends(6)

  if (isLoading) return <SkeletonRows rows={6} />
  if (!data || data.categories.length === 0) {
    return (
      <EmptyState
        title="Not enough history yet"
        hint="Trends need a few months of spending to compare against."
      />
    )
  }

  const flagged = data.categories.filter((c) => c.is_outlier).length

  return (
    <div className="flex flex-col gap-3">
      <p className="text-[var(--fg-muted)]">
        Each sparkline is {data.months.length} months of spending for one
        category; the dot is this month.{' '}
        {flagged > 0
          ? `${flagged} categor${flagged === 1 ? 'y is' : 'ies are'} more than 1.5σ off their own average (in orange).`
          : 'Nothing is more than 1.5σ off its own average this month.'}
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.categories.map((c) => (
          <Sparkline key={c.id} category={c} theme={theme} />
        ))}
      </div>
    </div>
  )
}

import { useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatCents } from '../../lib/money'
import { formatMonthLabel } from '../../lib/month'
import { useInsightsByCategory } from '../../lib/queries'
import type { GroupSpend } from '../../lib/types'
import { EmptyState, SkeletonRows } from '../ui'
import { useChartTheme } from './useChartTheme'

function currencyAxis(v: number): string {
  return formatCents(v).replace(/\.00$/, '')
}

function SpendChart({
  data,
  theme,
  onBarClick,
  compareLabel,
}: {
  data: { name: string; spent: number; compare: number }[]
  theme: ReturnType<typeof useChartTheme>
  onBarClick?: (name: string) => void
  compareLabel: string
}) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(160, data.length * 46)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 4, right: 24, bottom: 16, left: 8 }}
        barGap={2}
      >
        <defs>
          {/* Diagonal hatch so the reference (prior month) bar is distinct from
              the current month by pattern + outline, not colour alone. */}
          <pattern
            id="ref-hatch"
            width="5"
            height="5"
            patternTransform="rotate(45)"
            patternUnits="userSpaceOnUse"
          >
            <rect width="5" height="5" fill={theme.panel} />
            <line x1="0" y1="0" x2="0" y2="5" stroke={theme.subtle} strokeWidth="2" />
          </pattern>
        </defs>
        <CartesianGrid horizontal={false} stroke={theme.grid} />
        <XAxis
          type="number"
          tickFormatter={currencyAxis}
          stroke={theme.muted}
          tick={{ fill: theme.muted, fontSize: 11 }}
          label={{
            value: 'Spent (USD)',
            position: 'insideBottom',
            offset: -8,
            fill: theme.subtle,
            fontSize: 11,
          }}
        />
        <YAxis
          type="category"
          dataKey="name"
          width={110}
          stroke={theme.muted}
          tick={{ fill: theme.fg, fontSize: 12 }}
        />
        <Tooltip
          cursor={{ fill: theme.accentWeak }}
          contentStyle={{
            background: theme.panel,
            border: `1px solid ${theme.grid}`,
            color: theme.fg,
            fontSize: 12,
          }}
          formatter={(value: number, name: string) => [
            formatCents(value),
            name === 'spent' ? 'This month' : compareLabel,
          ]}
        />
        <Bar
          dataKey="compare"
          fill="url(#ref-hatch)"
          stroke={theme.subtle}
          strokeWidth={1}
          name="compare"
        />
        <Bar
          dataKey="spent"
          fill={theme.accent}
          name="spent"
          cursor={onBarClick ? 'pointer' : undefined}
          onClick={(d: { name?: string }) => onBarClick && d.name && onBarClick(d.name)}
        >
          {data.map((entry) => (
            <Cell key={entry.name} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

export function ByCategoryView({ month }: { month: string }) {
  const theme = useChartTheme()
  const { data, isLoading } = useInsightsByCategory(month)
  const [expanded, setExpanded] = useState<GroupSpend | null>(null)

  if (isLoading) return <SkeletonRows rows={6} />
  if (!data || data.groups.length === 0) {
    return (
      <EmptyState
        title="No spending this month"
        hint={`Nothing was spent in ${formatMonthLabel(month)}.`}
      />
    )
  }

  const compareLabel = formatMonthLabel(data.compare_to)
  const groupData = data.groups.map((g) => ({
    name: g.name,
    spent: g.spent_cents,
    compare: g.compare_cents,
  }))
  const current = expanded
    ? data.groups.find((g) => g.id === expanded.id)
    : null

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-4 text-[12px] text-[var(--fg-muted)]">
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-3 w-4 rounded-sm"
            style={{ background: theme.accent }}
          />
          {formatMonthLabel(month)} (this month)
        </span>
        <span className="flex items-center gap-1.5">
          <span
            className="inline-block h-3 w-4 rounded-sm border"
            style={{
              borderColor: theme.subtle,
              backgroundImage: `repeating-linear-gradient(45deg, ${theme.subtle} 0 1.5px, transparent 1.5px 4px)`,
            }}
          />
          {compareLabel} (reference)
        </span>
      </div>
      <SpendChart
        data={groupData}
        theme={theme}
        compareLabel={compareLabel}
        onBarClick={(name) =>
          setExpanded(data.groups.find((g) => g.name === name) ?? null)
        }
      />
      <p className="text-[var(--fg-muted)]">
        Spending by category group in {formatMonthLabel(month)} (solid), with{' '}
        {compareLabel} shown faint for comparison. Click a bar to break a group
        into its categories.
      </p>

      {current && (
        <div className="rounded-md border border-[var(--border)] p-3">
          <div className="mb-2 flex items-center justify-between">
            <p className="font-medium text-[var(--fg)]">{current.name} categories</p>
            <button
              type="button"
              onClick={() => setExpanded(null)}
              className="rounded px-2 py-1 text-[var(--fg-muted)] hover:bg-[var(--row-hover)]"
            >
              Close
            </button>
          </div>
          {current.categories.length === 0 ? (
            <EmptyState title="No categories with spending" />
          ) : (
            <SpendChart
              data={current.categories.map((c) => ({
                name: c.name,
                spent: c.spent_cents,
                compare: c.compare_cents,
              }))}
              theme={theme}
              compareLabel={compareLabel}
            />
          )}
        </div>
      )}
    </div>
  )
}

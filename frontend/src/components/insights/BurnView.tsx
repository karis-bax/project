import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatCents } from '../../lib/money'
import { formatMonthLabel } from '../../lib/month'
import { useInsightsBurn } from '../../lib/queries'
import { EmptyState, SkeletonRows } from '../ui'
import { useChartTheme } from './useChartTheme'

function currencyAxis(v: number): string {
  return formatCents(v).replace(/\.00$/, '')
}

export function BurnView({ month }: { month: string }) {
  const theme = useChartTheme()
  const { data, isLoading } = useInsightsBurn(month)

  if (isLoading) return <SkeletonRows rows={6} />
  if (!data || (data.current.length === 0 && data.history.every((h) => h.points.length === 0))) {
    return (
      <EmptyState
        title="No spending to chart"
        hint={`Nothing was spent in ${formatMonthLabel(month)} or the prior three months.`}
      />
    )
  }

  // Combine into one row per day-of-month.
  const rows: Record<number, Record<string, number | null>> = {}
  for (let day = 1; day <= data.days_in_month; day++) {
    rows[day] = { day }
  }
  for (const p of data.current) rows[p.day].current = p.cumulative_cents
  data.history.forEach((series, i) => {
    for (const p of series.points) {
      if (rows[p.day]) rows[p.day][`h${i}`] = p.cumulative_cents
    }
  })
  // Dashed projection from the last actual point to the projected month-end total.
  if (data.projected_total_cents !== null && data.current.length > 0) {
    const last = data.current[data.current.length - 1]
    rows[last.day].projection = last.cumulative_cents
    rows[data.days_in_month].projection = data.projected_total_cents
  }
  const chartData = Object.values(rows)

  const historyColors = [theme.subtle, theme.grid, theme.muted]

  return (
    <div className="flex flex-col gap-3">
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData} margin={{ top: 8, right: 24, bottom: 24, left: 8 }}>
          <CartesianGrid stroke={theme.grid} />
          <XAxis
            dataKey="day"
            stroke={theme.muted}
            tick={{ fill: theme.muted, fontSize: 11 }}
            label={{
              value: 'Day of month',
              position: 'insideBottom',
              offset: -12,
              fill: theme.subtle,
              fontSize: 11,
            }}
          />
          <YAxis
            tickFormatter={currencyAxis}
            stroke={theme.muted}
            tick={{ fill: theme.muted, fontSize: 11 }}
            width={72}
            label={{
              value: 'Cumulative spend (USD)',
              angle: -90,
              position: 'insideLeft',
              fill: theme.subtle,
              fontSize: 11,
              style: { textAnchor: 'middle' },
            }}
          />
          <Tooltip
            contentStyle={{
              background: theme.panel,
              border: `1px solid ${theme.grid}`,
              color: theme.fg,
              fontSize: 12,
            }}
            labelFormatter={(d: number) => `Day ${d}`}
            formatter={(v: number, key: string) => [
              formatCents(v),
              key === 'current'
                ? formatMonthLabel(data.month)
                : key === 'projection'
                  ? 'Projected'
                  : formatMonthLabel(data.history[Number(key.slice(1))]?.month ?? ''),
            ]}
          />
          <Legend
            wrapperStyle={{ fontSize: 11, color: theme.muted }}
            formatter={(value: string) =>
              value === 'current'
                ? formatMonthLabel(data.month)
                : value === 'projection'
                  ? 'Projected'
                  : formatMonthLabel(data.history[Number(value.slice(1))]?.month ?? '')
            }
          />
          {data.history.map((_series, i) => (
            <Line
              key={`h${i}`}
              type="monotone"
              dataKey={`h${i}`}
              stroke={historyColors[i % historyColors.length]}
              strokeWidth={1}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
          <Line
            type="monotone"
            dataKey="projection"
            stroke={theme.warn}
            strokeWidth={1.5}
            strokeDasharray="5 4"
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="current"
            stroke={theme.accent}
            strokeWidth={2}
            dot={false}
            connectNulls
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-[var(--fg-muted)]">
        Cumulative spending this month against the prior three months.{' '}
        {data.projected_total_cents !== null && (
          <>
            At the current pace this month lands near{' '}
            <span className="num tabular-nums text-[var(--fg)]">
              {formatCents(data.projected_total_cents)}
            </span>
            . {data.assumption}
          </>
        )}
      </p>
    </div>
  )
}

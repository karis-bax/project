import type { ReactNode } from 'react'

import { formatCents } from '../lib/money'

/** A single shimmering skeleton bar. */
export function Skeleton({
  width = '100%',
  height = 12,
  className = '',
}: {
  width?: number | string
  height?: number | string
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={`skeleton block ${className}`}
      style={{ width, height }}
    />
  )
}

/** A stack of skeleton rows, used as a real loading state (never "Loading..."). */
export function SkeletonRows({
  rows = 5,
  className = '',
}: {
  rows?: number
  className?: string
}) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label="Loading"
      className={`flex flex-col gap-2 ${className}`}
    >
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center justify-between gap-4 py-1.5">
          <Skeleton width={`${40 + ((i * 13) % 45)}%`} />
          <Skeleton width={64} />
        </div>
      ))}
    </div>
  )
}

/** A quiet empty state with a title and optional hint / action. */
export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-md border border-dashed border-[var(--border-strong)] px-6 py-12 text-center">
      <p className="text-[var(--fg)] font-medium">{title}</p>
      {hint && <p className="max-w-sm text-[var(--fg-muted)]">{hint}</p>}
      {action}
    </div>
  )
}

/** A placeholder for screens whose feature UI lands in a later phase. */
export function Placeholder({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border-strong)] px-6 py-12 text-center">
      <p className="text-[var(--fg)] font-medium">{title}</p>
      {hint && <p className="mt-1 text-[var(--fg-muted)]">{hint}</p>}
    </div>
  )
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-md border border-[var(--border-strong)] bg-[var(--panel-raised)] px-4 py-3 text-[var(--fg)]">
      <p className="font-medium">Something went wrong</p>
      <p className="text-[var(--fg-muted)]">{message}</p>
    </div>
  )
}

/**
 * Money display. Positive amounts use the single accent hue; negative and zero
 * amounts stay quiet. Uses tabular numerals so figures align in a column.
 */
export function Money({
  cents,
  sign = false,
  className = '',
}: {
  cents: number
  sign?: boolean
  className?: string
}) {
  const color = cents > 0 ? 'text-[var(--pos)]' : 'text-[var(--neg)]'
  return (
    <span className={`num ${color} ${className}`}>
      {formatCents(cents, { sign })}
    </span>
  )
}

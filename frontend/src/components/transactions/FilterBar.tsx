import { useAccounts, useTransactionsCount } from '../../lib/queries'
import type { TransactionFilters } from '../../lib/queries'
import { CategorySelect } from './CategorySelect'

export function FilterBar({
  filters,
  onChange,
}: {
  filters: TransactionFilters
  onChange: (next: TransactionFilters) => void
}) {
  const accounts = useAccounts()

  // Live count of uncategorized transactions under the other active filters
  // (month / account / search), ignoring the category + uncategorized filters.
  const badge = useTransactionsCount({
    month: filters.month,
    account_id: filters.account_id,
    q: filters.q,
    uncategorized: true,
  })

  const patch = (part: Partial<TransactionFilters>) =>
    onChange({ ...filters, ...part })

  const control =
    'rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none'

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        type="month"
        aria-label="Month"
        className={control}
        value={filters.month ?? ''}
        onChange={(e) => patch({ month: e.target.value || undefined })}
      />

      <select
        aria-label="Account"
        className={control}
        value={filters.account_id ?? ''}
        onChange={(e) =>
          patch({ account_id: e.target.value ? Number(e.target.value) : undefined })
        }
      >
        <option value="">All accounts</option>
        {(accounts.data ?? []).map((a) => (
          <option key={a.id} value={a.id}>
            {a.name}
          </option>
        ))}
      </select>

      <CategorySelect
        ariaLabel="Category filter"
        emptyLabel="All categories"
        value={filters.category_id ?? null}
        onChange={(v) => patch({ category_id: v ?? undefined })}
      />

      <input
        type="search"
        aria-label="Search payee or memo"
        placeholder="Search payee or memo…"
        className={`${control} min-w-48 flex-1`}
        value={filters.q ?? ''}
        onChange={(e) => patch({ q: e.target.value || undefined })}
      />

      <button
        type="button"
        aria-pressed={Boolean(filters.uncategorized)}
        onClick={() =>
          patch({ uncategorized: filters.uncategorized ? undefined : true })
        }
        className={`flex items-center gap-1.5 rounded border px-2.5 py-1 ${
          filters.uncategorized
            ? 'border-[var(--accent)] bg-[var(--accent-weak)] text-[var(--accent)]'
            : 'border-[var(--border)] text-[var(--fg-muted)] hover:bg-[var(--row-hover)]'
        }`}
      >
        Uncategorized only
        {badge.data !== undefined && (
          <span
            className={`num rounded-full px-1.5 text-[11px] tabular-nums ${
              filters.uncategorized
                ? 'bg-[var(--accent)] text-[var(--accent-fg)]'
                : 'bg-[var(--border)] text-[var(--fg-muted)]'
            }`}
          >
            {badge.data.count}
          </span>
        )}
      </button>
    </div>
  )
}

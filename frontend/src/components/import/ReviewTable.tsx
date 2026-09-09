import { useMemo, useState } from 'react'

import { formatCents } from '../../lib/money'
import type { ImportCommitRow, ImportPreviewResponse } from '../../lib/types'
import { CategorySelect } from '../transactions/CategorySelect'

const COLS = '2.5rem 6.5rem 1fr 12rem 8rem'

export function ReviewTable({
  preview,
  committing,
  onBack,
  onCommit,
}: {
  preview: ImportPreviewResponse
  committing: boolean
  onBack: () => void
  onCommit: (rows: ImportCommitRow[], skipDuplicates: boolean) => void
}) {
  const rows = preview.rows
  const [checked, setChecked] = useState<Record<number, boolean>>(() =>
    Object.fromEntries(
      rows.map((r) => [r.row_index, r.importable && !r.is_duplicate]),
    ),
  )
  const [categories, setCategories] = useState<Record<number, number | null>>(() =>
    Object.fromEntries(rows.map((r) => [r.row_index, r.proposed_category_id])),
  )
  const [skipDuplicates, setSkipDuplicates] = useState(true)

  const importableCount = rows.filter((r) => r.importable).length
  const duplicateCount = rows.filter((r) => r.importable && r.is_duplicate).length
  const selected = rows.filter((r) => checked[r.row_index])
  const uncategorizedCount = selected.filter(
    (r) => categories[r.row_index] == null,
  ).length

  const commitRows = useMemo(
    (): ImportCommitRow[] =>
      selected
        .filter((r) => r.date !== null && r.amount_cents !== null)
        .map((r) => ({
          date: r.date as string,
          payee: r.payee,
          amount_cents: r.amount_cents as number,
          memo: r.memo,
          category_id: categories[r.row_index] ?? null,
          is_duplicate: r.is_duplicate,
        })),
    [selected, categories],
  )

  return (
    <div className="flex flex-col gap-3">
      {preview.warnings.length > 0 && (
        <div className="rounded-md border border-[var(--warn)] bg-[var(--warn-weak)] px-3 py-2 text-[var(--warn)]">
          {preview.warnings.map((w, i) => (
            <p key={i}>{w}</p>
          ))}
        </div>
      )}

      {/* Summary bar */}
      <div className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--border)] bg-[var(--panel)] px-3 py-2">
        <span className="num font-medium tabular-nums text-[var(--fg)]">
          {importableCount} rows · {duplicateCount} duplicates
          {skipDuplicates ? ' skipped' : ''} · {uncategorizedCount} uncategorized
        </span>
        <label className="ml-auto flex items-center gap-2 text-[var(--fg-muted)]">
          <input
            type="checkbox"
            checked={skipDuplicates}
            onChange={(e) => {
              const skip = e.target.checked
              setSkipDuplicates(skip)
              // Re-toggle duplicate rows to match the skip preference.
              setChecked((prev) => {
                const next = { ...prev }
                for (const r of rows) {
                  if (r.importable && r.is_duplicate) next[r.row_index] = !skip
                }
                return next
              })
            }}
          />
          Skip duplicates
        </label>
      </div>

      <div className="overflow-auto rounded-md border border-[var(--border)]" style={{ maxHeight: 'calc(100vh - 22rem)' }}>
        <div
          className="sticky top-0 grid gap-2 border-b border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]"
          style={{ gridTemplateColumns: COLS }}
        >
          <span></span>
          <span>Date</span>
          <span>Payee</span>
          <span>Category</span>
          <span className="text-right">Amount</span>
        </div>

        {rows.map((r) => {
          const dup = r.importable && r.is_duplicate
          const muted = dup || !r.importable
          const reason = !r.importable
            ? r.warnings.join('; ') || 'Row is missing a date or amount'
            : dup
              ? 'Duplicate of an existing transaction (same account, date, amount, and payee)'
              : undefined
          return (
            <div
              key={r.row_index}
              title={reason}
              className={`grid items-center gap-2 border-b border-[var(--border)] px-3 py-1.5 ${
                muted ? 'opacity-50' : ''
              }`}
              style={{ gridTemplateColumns: COLS }}
            >
              <input
                type="checkbox"
                disabled={!r.importable}
                checked={Boolean(checked[r.row_index])}
                onChange={(e) =>
                  setChecked((prev) => ({ ...prev, [r.row_index]: e.target.checked }))
                }
              />
              <span className="num tabular-nums text-[var(--fg-muted)]">
                {r.date ?? '—'}
              </span>
              <span className="truncate text-[var(--fg)]">
                {r.payee || <span className="italic text-[var(--fg-subtle)]">(no payee)</span>}
                {dup && (
                  <span className="ml-1.5 rounded bg-[var(--border)] px-1 text-[10px] uppercase text-[var(--fg-muted)]">
                    dup
                  </span>
                )}
              </span>
              <CategorySelect
                ariaLabel={`Category for ${r.payee}`}
                emptyLabel="Uncategorized"
                value={categories[r.row_index] ?? null}
                onChange={(v) =>
                  setCategories((prev) => ({ ...prev, [r.row_index]: v }))
                }
                className="w-full"
              />
              <span className="num text-right tabular-nums text-[var(--fg)]">
                {r.amount_cents === null ? '—' : formatCents(r.amount_cents, { sign: true })}
              </span>
            </div>
          )
        })}
      </div>

      <div className="flex items-center justify-between">
        <button
          type="button"
          onClick={onBack}
          className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--fg-muted)] hover:bg-[var(--row-hover)]"
        >
          Back
        </button>
        <button
          type="button"
          onClick={() => onCommit(commitRows, skipDuplicates)}
          disabled={committing || commitRows.length === 0}
          className="rounded bg-[var(--accent)] px-4 py-1.5 text-[var(--accent-fg)] disabled:opacity-50"
        >
          {committing ? 'Importing…' : `Import ${commitRows.length} transactions`}
        </button>
      </div>
    </div>
  )
}

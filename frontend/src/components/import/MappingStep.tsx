import { parseDollars } from '../../lib/money'
import type { ImportMapping, ImportPreviewResponse } from '../../lib/types'

function magnitudeCents(raw: string): number | null {
  try {
    return Math.abs(parseDollars(raw))
  } catch {
    return null
  }
}

/** Client-side amount for the live 5-row preview (display only; the server is
 * authoritative once the mapping is applied). */
function previewAmount(cells: string[], mapping: ImportMapping): string {
  const at = (i: number | null) => (i === null ? '' : (cells[i] ?? ''))
  if (mapping.amount_shape === 'debit_credit') {
    const debit = magnitudeCents(at(mapping.debit_col))
    const credit = magnitudeCents(at(mapping.credit_col))
    if (debit) return `-${(debit / 100).toFixed(2)}`
    if (credit) return `${(credit / 100).toFixed(2)}`
    return ''
  }
  if (mapping.amount_shape === 'amount_type') {
    const mag = magnitudeCents(at(mapping.amount_col))
    if (mag === null) return ''
    const type = at(mapping.type_col).toLowerCase()
    const out = /debit|withdraw|payment|out|dr/.test(type)
    return `${out ? '-' : ''}${(mag / 100).toFixed(2)}`
  }
  return at(mapping.amount_col)
}

function ColumnSelect({
  label,
  columns,
  value,
  onChange,
}: {
  label: string
  columns: string[]
  value: number | null
  onChange: (value: number | null) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
      {label}
      <select
        className="rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
        value={value === null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      >
        <option value="">—</option>
        {columns.map((name, i) => (
          <option key={i} value={i}>
            {name}
          </option>
        ))}
      </select>
    </label>
  )
}

export function MappingStep({
  preview,
  mapping,
  onChange,
  onContinue,
  onBack,
  busy,
}: {
  preview: ImportPreviewResponse
  mapping: ImportMapping
  onChange: (mapping: ImportMapping) => void
  onContinue: () => void
  onBack: () => void
  busy: boolean
}) {
  const { columns, raw_sample } = preview
  const set = (part: Partial<ImportMapping>) => onChange({ ...mapping, ...part })

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          Amount format
          <select
            className="rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
            value={mapping.amount_shape}
            onChange={(e) =>
              set({ amount_shape: e.target.value as ImportMapping['amount_shape'] })
            }
          >
            <option value="signed">One signed amount column</option>
            <option value="debit_credit">Separate debit &amp; credit</option>
            <option value="amount_type">Amount + type column</option>
          </select>
        </label>

        <ColumnSelect
          label="Date"
          columns={columns}
          value={mapping.date_col}
          onChange={(v) => set({ date_col: v })}
        />
        <ColumnSelect
          label="Payee"
          columns={columns}
          value={mapping.payee_col}
          onChange={(v) => set({ payee_col: v })}
        />
        <ColumnSelect
          label="Memo"
          columns={columns}
          value={mapping.memo_col}
          onChange={(v) => set({ memo_col: v })}
        />

        {mapping.amount_shape === 'signed' && (
          <ColumnSelect
            label="Amount"
            columns={columns}
            value={mapping.amount_col}
            onChange={(v) => set({ amount_col: v })}
          />
        )}
        {mapping.amount_shape === 'debit_credit' && (
          <>
            <ColumnSelect
              label="Debit"
              columns={columns}
              value={mapping.debit_col}
              onChange={(v) => set({ debit_col: v })}
            />
            <ColumnSelect
              label="Credit"
              columns={columns}
              value={mapping.credit_col}
              onChange={(v) => set({ credit_col: v })}
            />
          </>
        )}
        {mapping.amount_shape === 'amount_type' && (
          <>
            <ColumnSelect
              label="Amount"
              columns={columns}
              value={mapping.amount_col}
              onChange={(v) => set({ amount_col: v })}
            />
            <ColumnSelect
              label="Type"
              columns={columns}
              value={mapping.type_col}
              onChange={(v) => set({ type_col: v })}
            />
          </>
        )}
      </div>

      {/* Live preview of the first five rows under the current mapping. */}
      <div className="rounded-md border border-[var(--border)]">
        <div
          className="grid gap-2 border-b border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]"
          style={{ gridTemplateColumns: '7rem 1fr 1fr 8rem' }}
        >
          <span>Date</span>
          <span>Payee</span>
          <span>Memo</span>
          <span className="text-right">Amount</span>
        </div>
        {raw_sample.map((cells, i) => (
          <div
            key={i}
            className="grid gap-2 border-b border-[var(--border)] px-3 py-1.5 last:border-b-0"
            style={{ gridTemplateColumns: '7rem 1fr 1fr 8rem' }}
          >
            <span className="num tabular-nums text-[var(--fg-muted)]">
              {mapping.date_col === null ? '' : cells[mapping.date_col]}
            </span>
            <span className="truncate text-[var(--fg)]">
              {mapping.payee_col === null ? '' : cells[mapping.payee_col]}
            </span>
            <span className="truncate text-[var(--fg-muted)]">
              {mapping.memo_col === null ? '' : cells[mapping.memo_col]}
            </span>
            <span className="num text-right tabular-nums text-[var(--fg)]">
              {previewAmount(cells, mapping)}
            </span>
          </div>
        ))}
      </div>

      <div className="flex justify-between">
        <button
          type="button"
          onClick={onBack}
          className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--fg-muted)] hover:bg-[var(--row-hover)]"
        >
          Back
        </button>
        <button
          type="button"
          onClick={onContinue}
          disabled={busy}
          className="rounded bg-[var(--accent)] px-4 py-1.5 text-[var(--accent-fg)] disabled:opacity-50"
        >
          {busy ? 'Parsing…' : 'Continue to review'}
        </button>
      </div>
    </div>
  )
}

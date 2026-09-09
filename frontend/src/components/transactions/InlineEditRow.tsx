import { useState } from 'react'

import { formatCentsForInput, parseDollars } from '../../lib/money'
import {
  useDeleteTransaction,
  useUpdateTransaction,
} from '../../lib/queries'
import type { PayeeSuggestion, TransactionWithRelations } from '../../lib/types'
import { CategorySelect } from './CategorySelect'
import { PayeeCombobox } from './PayeeCombobox'

export function InlineEditRow({
  transaction,
  payees,
  onClose,
  onDeleted,
}: {
  transaction: TransactionWithRelations
  payees: PayeeSuggestion[]
  onClose: () => void
  onDeleted?: (id: number, payee: string) => void
}) {
  const update = useUpdateTransaction()
  const remove = useDeleteTransaction()

  const [date, setDate] = useState(transaction.date)
  const [payee, setPayee] = useState(transaction.payee)
  const [categoryId, setCategoryId] = useState<number | null>(
    transaction.category_id,
  )
  const [memo, setMemo] = useState(transaction.memo)
  const [amount, setAmount] = useState(formatCentsForInput(transaction.amount_cents))
  const [cleared, setCleared] = useState(transaction.cleared)
  const [error, setError] = useState<string | null>(null)

  const cell =
    'rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none'

  const save = () => {
    let amountCents: number
    try {
      amountCents = parseDollars(amount)
    } catch {
      setError('Enter a valid amount (e.g. -40 or 1234.56).')
      return
    }
    update.mutate(
      {
        id: transaction.id,
        body: {
          date,
          payee: payee.trim(),
          category_id: categoryId,
          memo: memo.trim(),
          amount_cents: amountCents,
          cleared,
        },
      },
      { onSuccess: onClose },
    )
  }

  return (
    <div className="border-y border-[var(--accent)] bg-[var(--accent-weak)] px-3 py-3">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          Date
          <input
            type="date"
            className={cell}
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          Payee
          <PayeeCombobox
            id={`edit-payee-${transaction.id}`}
            value={payee}
            payees={payees}
            onChange={setPayee}
            onPick={() => {}}
            className={cell}
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          Category
          <CategorySelect
            ariaLabel="Category"
            emptyLabel="Uncategorized"
            value={categoryId}
            onChange={setCategoryId}
            className="w-full"
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)] sm:col-span-2">
          Memo
          <input
            className={cell}
            value={memo}
            onChange={(e) => setMemo(e.target.value)}
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          Amount
          <input
            inputMode="decimal"
            className={`num text-right tabular-nums ${cell}`}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
          />
        </label>
      </div>

      <div className="mt-3 flex items-center justify-between">
        <label className="flex items-center gap-2 text-[var(--fg-muted)]">
          <input
            type="checkbox"
            checked={cleared}
            onChange={(e) => setCleared(e.target.checked)}
          />
          Cleared
        </label>
        <div className="flex items-center gap-2">
          {error && <span className="text-[var(--warn)]">{error}</span>}
          <button
            type="button"
            onClick={() =>
              remove.mutate(transaction.id, {
                onSuccess: () => {
                  onDeleted?.(transaction.id, transaction.payee)
                  onClose()
                },
              })
            }
            className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--warn)] hover:bg-[var(--warn-weak)]"
          >
            Delete
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--fg-muted)] hover:bg-[var(--row-hover)]"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={save}
            disabled={update.isPending}
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-[var(--accent-fg)] disabled:opacity-50"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  )
}

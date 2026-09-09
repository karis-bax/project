import { useRef, useState, type KeyboardEvent } from 'react'

import { parseAmountInput } from '../../lib/money'
import { useAccounts, useCreateTransaction, usePayees } from '../../lib/queries'
import type { PayeeSuggestion } from '../../lib/types'
import { CategorySelect } from './CategorySelect'
import { PayeeCombobox } from './PayeeCombobox'
import { REGISTER_COLS, todayISO } from './layout'

interface Draft {
  date: string
  payee: string
  categoryId: number | null
  categorySuggested: boolean
  amount: string
  memo: string
}

function emptyDraft(): Draft {
  return {
    date: todayISO(),
    payee: '',
    categoryId: null,
    categorySuggested: false,
    amount: '',
    memo: '',
  }
}

export function QuickAddRow() {
  const accounts = useAccounts()
  const payees = usePayees()
  const create = useCreateTransaction()
  const payeeRef = useRef<HTMLInputElement | null>(null)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [accountId, setAccountId] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const activeAccountId = accountId ?? accounts.data?.[0]?.id ?? null

  const patch = (part: Partial<Draft>) => setDraft((d) => ({ ...d, ...part }))

  const handlePick = (s: PayeeSuggestion) => {
    // Auto-fill the most-frequent category, but leave it editable and marked as
    // a suggestion.
    if (s.suggested_category_id !== null) {
      setDraft((d) => ({
        ...d,
        categoryId: s.suggested_category_id,
        categorySuggested: true,
      }))
    }
  }

  const save = () => {
    if (activeAccountId === null) {
      setError('Add an account first.')
      return
    }
    if (!draft.payee.trim()) {
      setError('Payee is required.')
      payeeRef.current?.focus()
      return
    }
    let amountCents: number
    try {
      amountCents = parseAmountInput(draft.amount)
    } catch {
      setError('Enter an amount like 12.50, -40, or +1,234.56')
      return
    }
    setError(null)
    create.mutate(
      {
        account_id: activeAccountId,
        category_id: draft.categoryId,
        date: draft.date,
        payee: draft.payee.trim(),
        amount_cents: amountCents,
        memo: draft.memo.trim(),
        cleared: false,
        pending: false,
        import_hash: null,
      },
      {
        onSuccess: () => {
          // Reset for rapid entry: keep date + account, focus payee.
          setDraft((d) => ({ ...emptyDraft(), date: d.date }))
          payeeRef.current?.focus()
        },
      },
    )
  }

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      save()
    }
  }

  const cell =
    'rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none'

  return (
    <div className="border-b border-[var(--border-strong)] bg-[var(--panel)]">
      <div className="flex items-center gap-2 px-3 pt-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
        <span>Quick add</span>
        <select
          aria-label="Account"
          tabIndex={-1}
          className="rounded border border-[var(--border)] bg-[var(--panel-raised)] px-1.5 py-0.5 text-[11px] normal-case text-[var(--fg-muted)]"
          value={activeAccountId ?? ''}
          onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
        >
          {(accounts.data ?? []).map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        {error && <span className="normal-case text-[var(--warn)]">{error}</span>}
      </div>

      {/*
        DOM order follows the required tab order (date, payee, category, amount,
        memo); explicit grid-column keeps the visual columns aligned with the
        register (…, memo, amount, …).
      */}
      <div
        className="grid items-center gap-2 px-3 py-2"
        style={{ gridTemplateColumns: REGISTER_COLS }}
      >
        <input
          type="date"
          aria-label="Date"
          className={cell}
          style={{ gridColumn: 1 }}
          value={draft.date}
          onChange={(e) => patch({ date: e.target.value })}
          onKeyDown={onKeyDown}
        />
        <div style={{ gridColumn: 2 }} className="flex">
          <PayeeCombobox
            id="quickadd-payee"
            value={draft.payee}
            payees={payees.data ?? []}
            onChange={(v) => patch({ payee: v })}
            onPick={handlePick}
            inputRef={(el) => (payeeRef.current = el)}
            onKeyDown={onKeyDown}
            className={`w-full ${cell}`}
          />
        </div>
        <div style={{ gridColumn: 3 }} className="flex items-center gap-1">
          <CategorySelect
            ariaLabel="Category"
            emptyLabel="Uncategorized"
            value={draft.categoryId}
            onChange={(v) => patch({ categoryId: v, categorySuggested: false })}
            onKeyDown={onKeyDown}
            className={`min-w-0 flex-1 ${
              draft.categorySuggested ? 'italic text-[var(--accent)]' : ''
            }`}
          />
          {draft.categorySuggested && (
            <span
              title="Suggested from this payee's history"
              className="shrink-0 rounded bg-[var(--accent-weak)] px-1 text-[10px] text-[var(--accent)]"
            >
              sug
            </span>
          )}
        </div>
        <input
          aria-label="Amount"
          inputMode="decimal"
          placeholder="-0.00"
          className={`num text-right tabular-nums ${cell}`}
          style={{ gridColumn: 5 }}
          value={draft.amount}
          onChange={(e) => patch({ amount: e.target.value })}
          onKeyDown={onKeyDown}
        />
        <input
          aria-label="Memo"
          placeholder="Memo"
          className={cell}
          style={{ gridColumn: 4 }}
          value={draft.memo}
          onChange={(e) => patch({ memo: e.target.value })}
          onKeyDown={onKeyDown}
        />
        <button
          type="button"
          onClick={save}
          disabled={create.isPending}
          aria-label="Add transaction"
          className="justify-self-center rounded bg-[var(--accent)] px-2 py-1 text-[var(--accent-fg)] disabled:opacity-50"
          style={{ gridColumn: 6 }}
          tabIndex={-1}
        >
          +
        </button>
      </div>
    </div>
  )
}

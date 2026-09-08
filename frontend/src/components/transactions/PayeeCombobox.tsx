import type { KeyboardEvent } from 'react'

import type { PayeeSuggestion } from '../../lib/types'

/**
 * Payee input that autocompletes from distinct existing payees (native
 * datalist). When the value exactly matches a known payee, `onPick` fires with
 * that payee's suggestion (used to auto-fill its most-frequent category).
 */
export function PayeeCombobox({
  id,
  value,
  onChange,
  onPick,
  payees,
  className = '',
  tabIndex,
  placeholder = 'Payee',
  inputRef,
  onKeyDown,
}: {
  id: string
  value: string
  onChange: (value: string) => void
  onPick: (suggestion: PayeeSuggestion) => void
  payees: PayeeSuggestion[]
  className?: string
  tabIndex?: number
  placeholder?: string
  inputRef?: (el: HTMLInputElement | null) => void
  onKeyDown?: (e: KeyboardEvent<HTMLInputElement>) => void
}) {
  const listId = `${id}-payees`
  return (
    <>
      <input
        id={id}
        ref={inputRef}
        list={listId}
        autoComplete="off"
        placeholder={placeholder}
        tabIndex={tabIndex}
        className={`rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none ${className}`}
        value={value}
        onChange={(e) => {
          const next = e.target.value
          onChange(next)
          const match = payees.find(
            (p) => p.payee.toLowerCase() === next.toLowerCase(),
          )
          if (match) onPick(match)
        }}
        onKeyDown={onKeyDown}
      />
      <datalist id={listId}>
        {payees.map((p) => (
          <option key={p.payee} value={p.payee} />
        ))}
      </datalist>
    </>
  )
}

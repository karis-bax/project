import { useCategories } from '../../lib/queries'

/**
 * A <select> of categories grouped by their group. `null` represents the empty
 * option, whose meaning is set by `emptyLabel` (e.g. "All categories" for a
 * filter, or "Uncategorized" for an editor).
 */
export function CategorySelect({
  value,
  onChange,
  emptyLabel,
  className = '',
  tabIndex,
  ariaLabel,
  onKeyDown,
  selectRef,
}: {
  value: number | null
  onChange: (value: number | null) => void
  emptyLabel: string
  className?: string
  tabIndex?: number
  ariaLabel?: string
  onKeyDown?: (e: React.KeyboardEvent<HTMLSelectElement>) => void
  selectRef?: (el: HTMLSelectElement | null) => void
}) {
  const { data } = useCategories()

  return (
    <select
      ref={selectRef}
      aria-label={ariaLabel}
      tabIndex={tabIndex}
      className={`rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none ${className}`}
      value={value === null ? '' : String(value)}
      onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      onKeyDown={onKeyDown}
    >
      <option value="">{emptyLabel}</option>
      {(data ?? []).map((group) => (
        <optgroup key={group.id} label={group.name}>
          {group.categories.map((cat) => (
            <option key={cat.id} value={cat.id}>
              {cat.name}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

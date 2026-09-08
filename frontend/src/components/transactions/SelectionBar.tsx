import {
  useBulkCategorize,
  useMarkTransactionsCleared,
} from '../../lib/queries'
import { CategorySelect } from './CategorySelect'

export function SelectionBar({
  selectedIds,
  onClear,
}: {
  selectedIds: number[]
  onClear: () => void
}) {
  const categorize = useBulkCategorize()
  const markCleared = useMarkTransactionsCleared()

  return (
    <div className="flex flex-wrap items-center gap-3 rounded-md border border-[var(--accent)] bg-[var(--accent-weak)] px-3 py-2">
      <span className="num font-medium tabular-nums text-[var(--accent)]">
        {selectedIds.length} selected
      </span>

      <div className="flex items-center gap-1.5">
        <span className="text-[var(--fg-muted)]">Categorize as</span>
        <CategorySelect
          ariaLabel="Categorize selected as"
          emptyLabel="Choose…"
          value={null}
          onChange={(categoryId) => {
            if (categoryId === null) return
            categorize.mutate(
              { ids: selectedIds, category_id: categoryId },
              { onSuccess: onClear },
            )
          }}
        />
      </div>

      <button
        type="button"
        onClick={() =>
          markCleared.mutate(
            { ids: selectedIds, cleared: true },
            { onSuccess: onClear },
          )
        }
        disabled={markCleared.isPending}
        className="rounded border border-[var(--border-strong)] bg-[var(--panel-raised)] px-3 py-1.5 text-[var(--fg)] hover:bg-[var(--row-hover)] disabled:opacity-50"
      >
        Mark cleared
      </button>

      <button
        type="button"
        onClick={onClear}
        className="ml-auto rounded px-2 py-1 text-[var(--fg-muted)] hover:bg-[var(--row-hover)]"
      >
        Clear selection
      </button>
    </div>
  )
}

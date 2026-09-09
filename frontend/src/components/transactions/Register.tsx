import { useEffect, useRef, type ReactNode } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'

import { formatCents } from '../../lib/money'
import { useUpdateTransaction } from '../../lib/queries'
import type { PayeeSuggestion, TransactionWithRelations } from '../../lib/types'
import { InlineEditRow } from './InlineEditRow'
import { QuickAddRow } from './QuickAddRow'
import { REGISTER_COLS, formatShortDate } from './layout'

export interface ActivateModifiers {
  shift: boolean
  meta: boolean
}

function AmountText({ cents }: { cents: number }) {
  const income = cents > 0
  return (
    <span
      className={`num tabular-nums ${income ? 'font-medium text-[var(--accent)]' : 'text-[var(--fg)]'}`}
    >
      {/* Explicit +/- sign distinguishes inflow vs outflow without relying on
          color alone. */}
      {formatCents(cents, { sign: true })}
    </span>
  )
}

function DisplayRow({
  txn,
  index,
  selected,
  onActivate,
}: {
  txn: TransactionWithRelations
  index: number
  selected: boolean
  onActivate: (id: number, index: number, mods: ActivateModifiers) => void
}) {
  const update = useUpdateTransaction()
  const activate = (e: { shiftKey: boolean; metaKey: boolean; ctrlKey: boolean }) =>
    onActivate(txn.id, index, {
      shift: e.shiftKey,
      meta: e.metaKey || e.ctrlKey,
    })
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Transaction ${txn.payee}, ${formatShortDate(txn.date)}`}
      onClick={(e) => activate(e)}
      onKeyDown={(e) => {
        // Only when the row itself is focused — not the checkbox/link inside it.
        if (e.target !== e.currentTarget) return
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault() // Space would otherwise scroll
          activate(e)
        }
      }}
      className={`grid cursor-pointer items-center gap-2 border-b border-[var(--border)] px-3 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-[var(--accent)] ${
        selected ? 'bg-[var(--accent-weak)]' : 'hover:bg-[var(--row-hover)]'
      }`}
      style={{ gridTemplateColumns: REGISTER_COLS }}
    >
      <span className="num tabular-nums text-[var(--fg-muted)]">
        {formatShortDate(txn.date)}
      </span>
      <span className="truncate text-[var(--fg)]">{txn.payee}</span>
      <span className="truncate">
        {txn.category ? (
          <span className="text-[var(--fg-muted)]">{txn.category.name}</span>
        ) : (
          <span className="italic text-[var(--fg-subtle)]">Uncategorized</span>
        )}
      </span>
      <span className="truncate text-[var(--fg-muted)]">{txn.memo}</span>
      <span className="text-right">
        <AmountText cents={txn.amount_cents} />
      </span>
      <span className="flex justify-center">
        <input
          type="checkbox"
          aria-label={txn.cleared ? 'Cleared' : 'Not cleared'}
          checked={txn.cleared}
          onClick={(e) => e.stopPropagation()}
          onChange={(e) =>
            update.mutate({ id: txn.id, body: { cleared: e.target.checked } })
          }
        />
      </span>
    </div>
  )
}

export function Register({
  items,
  payees,
  hasNextPage,
  isFetchingNextPage,
  fetchNextPage,
  selectedIds,
  editingId,
  onActivate,
  onCloseEdit,
  emptyState,
}: {
  items: TransactionWithRelations[]
  payees: PayeeSuggestion[]
  hasNextPage: boolean
  isFetchingNextPage: boolean
  fetchNextPage: () => void
  selectedIds: Set<number>
  editingId: number | null
  onActivate: (id: number, index: number, mods: ActivateModifiers) => void
  onCloseEdit: () => void
  emptyState: ReactNode
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null)

  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 34,
    overscan: 12,
  })

  const virtualItems = virtualizer.getVirtualItems()

  // Infinite scroll: fetch the next page as the last row comes into view.
  useEffect(() => {
    const last = virtualItems[virtualItems.length - 1]
    if (!last) return
    if (last.index >= items.length - 1 && hasNextPage && !isFetchingNextPage) {
      fetchNextPage()
    }
  }, [virtualItems, items.length, hasNextPage, isFetchingNextPage, fetchNextPage])

  return (
    <div className="overflow-hidden rounded-md border border-[var(--border)]">
      {/* Column header (pinned) */}
      <div
        className="grid items-center gap-2 border-b border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]"
        style={{ gridTemplateColumns: REGISTER_COLS }}
      >
        <span>Date</span>
        <span>Payee</span>
        <span>Category</span>
        <span>Memo</span>
        <span className="text-right">Amount</span>
        <span className="text-center">Clr</span>
      </div>

      {/* Quick-add (pinned) */}
      <QuickAddRow />

      {/* Virtualized body */}
      <div
        ref={scrollRef}
        className="overflow-auto"
        style={{ height: 'calc(100vh - 15rem)' }}
      >
        {items.length === 0 ? (
          <div className="p-4">{emptyState}</div>
        ) : (
        <div
          style={{ height: virtualizer.getTotalSize(), position: 'relative' }}
        >
          {virtualItems.map((vi) => {
            const txn = items[vi.index]
            const editing = editingId === txn.id
            return (
              <div
                key={txn.id}
                data-index={vi.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${vi.start}px)`,
                }}
              >
                {editing ? (
                  <InlineEditRow
                    transaction={txn}
                    payees={payees}
                    onClose={onCloseEdit}
                  />
                ) : (
                  <DisplayRow
                    txn={txn}
                    index={vi.index}
                    selected={selectedIds.has(txn.id)}
                    onActivate={onActivate}
                  />
                )}
              </div>
            )
          })}
        </div>
        )}
        {isFetchingNextPage && (
          <div className="px-3 py-2 text-center text-[var(--fg-subtle)]">
            Loading more…
          </div>
        )}
      </div>
    </div>
  )
}

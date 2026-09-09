import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'

import { api } from '../../lib/api'
import { formatCents, formatCentsForInput, parseDollars } from '../../lib/money'
import { queryKeys } from '../../lib/queries'
import { useCollapsedGroups } from '../../lib/useCollapsedGroups'
import { AvailableCell } from './AvailableCell'
import { neighborId } from './gridNav'
import type {
  CategoryBudgetRow,
  GoalRead,
  GroupBudget,
  MonthBudget,
} from '../../lib/types'

const GRID_COLS = 'minmax(0,1fr) 8.5rem 8.5rem 8.5rem'

/** Patch only the edited category's assigned value in the cached budget.
 * Deliberately does NOT touch available, group subtotals, or left_to_assign —
 * those are server-owned and refreshed by the refetch on settle. */
function patchAssigned(
  budget: MonthBudget,
  categoryId: number,
  cents: number,
): MonthBudget {
  return {
    ...budget,
    groups: budget.groups.map((group) => ({
      ...group,
      categories: group.categories.map((cat) =>
        cat.id === categoryId ? { ...cat, assigned_cents: cents } : cat,
      ),
    })),
  }
}

interface CommitVars {
  categoryId: number
  amountCents: number
}

// --- Assigned (inline-editable) cell ---------------------------------------

function AssignedCell({
  category,
  registerRef,
  onCommit,
  onNavigate,
}: {
  category: CategoryBudgetRow
  registerRef: (id: number, el: HTMLInputElement | null) => void
  onCommit: (category: CategoryBudgetRow, cents: number) => void
  onNavigate: (id: number, direction: 1 | -1) => boolean
}) {
  const [draft, setDraft] = useState<string | null>(null)
  const editing = draft !== null
  const display = editing ? draft : formatCents(category.assigned_cents)

  const commit = () => {
    if (draft === null) return
    let cents: number
    try {
      cents = parseDollars(draft)
    } catch {
      setDraft(null) // invalid input reverts, like Escape
      return
    }
    setDraft(null)
    if (cents !== category.assigned_cents) {
      onCommit(category, cents)
    }
  }

  return (
    <input
      ref={(el) => registerRef(category.id, el)}
      inputMode="decimal"
      aria-label={`Assigned for ${category.name}`}
      className="num w-full rounded border border-transparent bg-transparent px-2 py-1 text-right tabular-nums text-[var(--fg)] hover:border-[var(--border)] focus:border-[var(--accent)] focus:bg-[var(--panel-raised)] focus:outline-none"
      value={display}
      onFocus={(e) => {
        setDraft(formatCentsForInput(category.assigned_cents))
        const el = e.currentTarget
        requestAnimationFrame(() => el.select())
      }}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        switch (e.key) {
          case 'Enter':
            e.preventDefault()
            commit()
            onNavigate(category.id, 1)
            break
          case 'Tab': {
            // Commit, then move within the grid only if there IS a neighbour.
            // At the first/last cell let Tab/Shift+Tab leave the grid (no trap).
            commit()
            const moved = onNavigate(category.id, e.shiftKey ? -1 : 1)
            if (moved) e.preventDefault()
            break
          }
          case 'ArrowDown':
            e.preventDefault()
            commit()
            onNavigate(category.id, 1)
            break
          case 'ArrowUp':
            e.preventDefault()
            commit()
            onNavigate(category.id, -1)
            break
          case 'Escape':
            e.preventDefault()
            setDraft(null)
            e.currentTarget.blur()
            break
        }
      }}
    />
  )
}

// --- Grid ------------------------------------------------------------------

export function EnvelopeGrid({
  month,
  data,
  goals,
}: {
  month: string
  data: MonthBudget
  goals: GoalRead[]
}) {
  const queryClient = useQueryClient()
  const { isCollapsed, toggle } = useCollapsedGroups()
  const inputRefs = useRef(new Map<number, HTMLInputElement | null>())
  // Remembers the single most recent committed allocation, for Cmd/Ctrl+Z undo.
  const lastCommit = useRef<{ categoryId: number; prevCents: number } | null>(null)

  const goalByCategory = useMemo(() => {
    const map = new Map<number, GoalRead>()
    for (const goal of goals) {
      if (!map.has(goal.category_id)) map.set(goal.category_id, goal)
    }
    return map
  }, [goals])

  const visibleIds = useMemo(() => {
    const ids: number[] = []
    for (const group of data.groups) {
      if (isCollapsed(group.id)) continue
      for (const cat of group.categories) ids.push(cat.id)
    }
    return ids
  }, [data.groups, isCollapsed])

  const mutation = useMutation({
    mutationFn: ({ categoryId, amountCents }: CommitVars) =>
      api.put(`/budget/${month}/allocations/${categoryId}`, {
        amount_cents: amountCents,
      }),
    onMutate: async ({ categoryId, amountCents }: CommitVars) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.budget(month) })
      const previous = queryClient.getQueryData<MonthBudget>(
        queryKeys.budget(month),
      )
      if (previous) {
        // Optimistically show the typed value in the cell only. Left to assign
        // and available intentionally wait for the server response.
        queryClient.setQueryData(
          queryKeys.budget(month),
          patchAssigned(previous, categoryId, amountCents),
        )
      }
      return { previous }
    },
    onError: (_err, _vars, context) => {
      const ctx = context as { previous?: MonthBudget } | undefined
      if (ctx?.previous) {
        queryClient.setQueryData(queryKeys.budget(month), ctx.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.budget(month) })
    },
  })

  const registerRef = useCallback((id: number, el: HTMLInputElement | null) => {
    if (el) inputRefs.current.set(id, el)
    else inputRefs.current.delete(id)
  }, [])

  const focusRelative = useCallback(
    (id: number, direction: 1 | -1): boolean => {
      const next = neighborId(visibleIds, id, direction)
      if (next === undefined) return false
      inputRefs.current.get(next)?.focus()
      return true
    },
    [visibleIds],
  )

  const commitAllocation = useCallback(
    (category: CategoryBudgetRow, cents: number) => {
      lastCommit.current = {
        categoryId: category.id,
        prevCents: category.assigned_cents,
      }
      mutation.mutate({ categoryId: category.id, amountCents: cents })
    },
    [mutation],
  )

  // Cmd/Ctrl+Z undoes the single most recent allocation change.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z' && !e.shiftKey) {
        const last = lastCommit.current
        if (!last) return
        e.preventDefault()
        lastCommit.current = null
        mutation.mutate({
          categoryId: last.categoryId,
          amountCents: last.prevCents,
        })
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [mutation])

  return (
    <div className="rounded-md border border-[var(--border)]">
      <div
        className="grid items-center border-b border-[var(--border)] px-3 py-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]"
        style={{ gridTemplateColumns: GRID_COLS }}
      >
        <span>Category</span>
        <span className="text-right">Assigned</span>
        <span className="text-right">Activity</span>
        <span className="text-right">Available</span>
      </div>
      <div className="border-b border-[var(--border)] px-3 py-1 text-[11px] text-[var(--fg-subtle)]">
        Pending authorizations are shown under Available but are not deducted
        from it.
      </div>

      {data.groups.map((group) => (
        <GroupSection
          key={group.id}
          group={group}
          month={month}
          collapsed={isCollapsed(group.id)}
          onToggle={() => toggle(group.id)}
          goalByCategory={goalByCategory}
          registerRef={registerRef}
          onCommit={commitAllocation}
          onNavigate={focusRelative}
        />
      ))}
    </div>
  )
}

function GroupSection({
  group,
  month,
  collapsed,
  onToggle,
  goalByCategory,
  registerRef,
  onCommit,
  onNavigate,
}: {
  group: GroupBudget
  month: string
  collapsed: boolean
  onToggle: () => void
  goalByCategory: Map<number, GoalRead>
  registerRef: (id: number, el: HTMLInputElement | null) => void
  onCommit: (category: CategoryBudgetRow, cents: number) => void
  onNavigate: (id: number, direction: 1 | -1) => boolean
}) {
  return (
    <div className="border-b border-[var(--border)] last:border-b-0">
      <div
        className="grid items-center bg-[var(--panel)] px-3 py-1.5"
        style={{ gridTemplateColumns: GRID_COLS }}
      >
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={!collapsed}
          className="flex items-center gap-1.5 text-left font-medium text-[var(--fg)]"
        >
          <span className="w-3 text-[var(--fg-subtle)]" aria-hidden>
            {collapsed ? '▸' : '▾'}
          </span>
          {group.name}
        </button>
        <span className="num text-right tabular-nums text-[var(--fg-muted)]">
          {formatCents(group.assigned_cents)}
        </span>
        <span className="num text-right tabular-nums text-[var(--fg-muted)]">
          {formatCents(group.activity_cents)}
        </span>
        <span className="num text-right tabular-nums text-[var(--fg-muted)]">
          {formatCents(group.available_cents)}
        </span>
      </div>

      {!collapsed &&
        group.categories.map((category) => (
          <div
            key={category.id}
            className="grid items-center px-3 hover:bg-[var(--row-hover)]"
            style={{ gridTemplateColumns: GRID_COLS }}
          >
            <span className="truncate py-1 text-[var(--fg)]">{category.name}</span>
            <AssignedCell
              category={category}
              registerRef={registerRef}
              onCommit={onCommit}
              onNavigate={onNavigate}
            />
            <Link
              to={`/transactions?category_id=${category.id}&month=${month}`}
              className="num py-1 pr-2 text-right tabular-nums text-[var(--accent)] hover:underline"
            >
              {formatCents(category.activity_cents)}
            </Link>
            <AvailableCell
              category={category}
              goal={goalByCategory.get(category.id)}
              month={month}
            />
          </div>
        ))}
    </div>
  )
}

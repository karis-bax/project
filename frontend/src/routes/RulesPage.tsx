import { useMemo, useState } from 'react'

import { ApiError } from '../lib/api'
import {
  useApplyRules,
  useCategories,
  useCreateRule,
  useDeleteRule,
  useReorderRules,
  useRules,
} from '../lib/queries'
import type { RuleField } from '../lib/types'
import { CategorySelect } from '../components/transactions/CategorySelect'
import { EmptyState, ErrorState, SkeletonRows } from '../components/ui'

export function RulesPage() {
  const rules = useRules()
  const categories = useCategories(true)
  const createRule = useCreateRule()
  const deleteRule = useDeleteRule()
  const reorder = useReorderRules()
  const apply = useApplyRules()

  const [matchField, setMatchField] = useState<RuleField>('payee')
  const [pattern, setPattern] = useState('')
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [applied, setApplied] = useState<number | null>(null)

  const categoryName = useMemo(() => {
    const map = new Map<number, string>()
    for (const g of categories.data ?? []) {
      for (const c of g.categories) map.set(c.id, `${g.name} / ${c.name}`)
    }
    return map
  }, [categories.data])

  const list = rules.data ?? []

  const move = (index: number, direction: -1 | 1) => {
    const next = index + direction
    if (next < 0 || next >= list.length) return
    const ids = list.map((r) => r.id)
    ;[ids[index], ids[next]] = [ids[next], ids[index]]
    reorder.mutate(ids)
  }

  const submit = () => {
    if (!pattern.trim() || categoryId === null) return
    createRule.mutate(
      {
        match_field: matchField,
        pattern: pattern.trim(),
        category_id: categoryId,
        priority: 0,
      },
      {
        onSuccess: () => {
          setPattern('')
          setCategoryId(null)
        },
      },
    )
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-[var(--fg)]">Rules</h1>
          <p className="text-[var(--fg-muted)]">
            Auto-categorize transactions by matching the payee or memo. Higher
            rules win.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {applied !== null && (
            <span className="num tabular-nums text-[var(--accent)]">
              {applied} changed
            </span>
          )}
          <button
            type="button"
            onClick={() => apply.mutate(undefined, { onSuccess: (r) => setApplied(r.changed) })}
            disabled={apply.isPending || list.length === 0}
            className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--fg)] hover:bg-[var(--row-hover)] disabled:opacity-50"
          >
            {apply.isPending ? 'Applying…' : 'Apply to existing'}
          </button>
        </div>
      </div>

      {/* Create rule */}
      <div className="flex flex-wrap items-end gap-2 rounded-md border border-[var(--border)] px-3 py-3">
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          When
          <select
            className="rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)]"
            value={matchField}
            onChange={(e) => setMatchField(e.target.value as RuleField)}
          >
            <option value="payee">Payee</option>
            <option value="memo">Memo</option>
          </select>
        </label>
        <label className="flex flex-1 flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          contains
          <input
            className="rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
            placeholder="e.g. PUBLIX"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
          />
        </label>
        <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
          categorize as
          <CategorySelect emptyLabel="Choose…" value={categoryId} onChange={setCategoryId} />
        </label>
        <button
          type="button"
          onClick={submit}
          disabled={!pattern.trim() || categoryId === null || createRule.isPending}
          className="rounded bg-[var(--accent)] px-3 py-1.5 text-[var(--accent-fg)] disabled:opacity-50"
        >
          Add rule
        </button>
      </div>

      {rules.isLoading ? (
        <SkeletonRows rows={5} />
      ) : rules.isError ? (
        <ErrorState
          message={
            rules.error instanceof ApiError ? rules.error.detail : 'Failed to load rules.'
          }
        />
      ) : list.length === 0 ? (
        <EmptyState
          title="No rules yet"
          hint="Add a rule above, or create one from the import screen."
        />
      ) : (
        <div className="rounded-md border border-[var(--border)]">
          <div
            className="grid gap-2 border-b border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]"
            style={{ gridTemplateColumns: '4rem 5rem 1fr 1fr 6rem' }}
          >
            <span>Order</span>
            <span>Field</span>
            <span>Pattern</span>
            <span>Category</span>
            <span className="text-right">Actions</span>
          </div>
          {list.map((rule, index) => (
            <div
              key={rule.id}
              className="grid items-center gap-2 border-b border-[var(--border)] px-3 py-1.5 last:border-b-0"
              style={{ gridTemplateColumns: '4rem 5rem 1fr 1fr 6rem' }}
            >
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  aria-label="Move up"
                  disabled={index === 0 || reorder.isPending}
                  onClick={() => move(index, -1)}
                  className="rounded px-1 text-[var(--fg-muted)] hover:bg-[var(--row-hover)] disabled:opacity-30"
                >
                  ↑
                </button>
                <button
                  type="button"
                  aria-label="Move down"
                  disabled={index === list.length - 1 || reorder.isPending}
                  onClick={() => move(index, 1)}
                  className="rounded px-1 text-[var(--fg-muted)] hover:bg-[var(--row-hover)] disabled:opacity-30"
                >
                  ↓
                </button>
              </div>
              <span className="text-[var(--fg-muted)]">{rule.match_field}</span>
              <span className="truncate text-[var(--fg)]">{rule.pattern}</span>
              <span className="truncate text-[var(--fg-muted)]">
                {categoryName.get(rule.category_id) ?? `#${rule.category_id}`}
              </span>
              <span className="text-right">
                <button
                  type="button"
                  onClick={() => deleteRule.mutate(rule.id)}
                  className="rounded px-2 py-1 text-[var(--warn)] hover:bg-[var(--warn-weak)]"
                >
                  Delete
                </button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

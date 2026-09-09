import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { ApiError } from '../lib/api'
import {
  useAccounts,
  useCreateRule,
  useImportCommit,
  useImportPreview,
  useImportRemap,
} from '../lib/queries'
import type {
  ImportCommitResponse,
  ImportCommitRow,
  ImportMapping,
  ImportPreviewResponse,
} from '../lib/types'
import { CategorySelect } from '../components/transactions/CategorySelect'
import { DropZone } from '../components/import/DropZone'
import { MappingStep } from '../components/import/MappingStep'
import { ReviewTable } from '../components/import/ReviewTable'
import { ErrorState } from '../components/ui'

type Step = 'upload' | 'mapping' | 'review' | 'done'

function mostCommonUncategorizedPayee(rows: ImportCommitRow[]): string | null {
  const counts = new Map<string, number>()
  for (const r of rows) {
    if (r.category_id == null && r.payee) {
      counts.set(r.payee, (counts.get(r.payee) ?? 0) + 1)
    }
  }
  let best: string | null = null
  let bestN = 0
  for (const [payee, n] of counts) {
    if (n > bestN) {
      best = payee
      bestN = n
    }
  }
  return best
}

function ResultPanel({
  result,
  committedRows,
  onReset,
}: {
  result: ImportCommitResponse
  committedRows: ImportCommitRow[]
  onReset: () => void
}) {
  const createRule = useCreateRule()
  const suggestion = useMemo(
    () => mostCommonUncategorizedPayee(committedRows),
    [committedRows],
  )
  const [pattern, setPattern] = useState(suggestion ?? '')
  const [categoryId, setCategoryId] = useState<number | null>(null)
  const [ruleCreated, setRuleCreated] = useState(false)

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md border border-[var(--accent)] bg-[var(--accent-weak)] px-4 py-3">
        <p className="font-medium text-[var(--fg)]">Import complete</p>
        <p className="num tabular-nums text-[var(--fg-muted)]">
          {result.imported} imported · {result.skipped_duplicate} skipped as
          duplicate · {result.failed} failed
        </p>
      </div>

      {suggestion && (
        <div className="rounded-md border border-[var(--border)] px-4 py-3">
          <p className="font-medium text-[var(--fg)]">Create a rule from this</p>
          <p className="mb-2 text-[var(--fg-muted)]">
            “{suggestion}” was the most common uncategorized payee. Create a rule
            so it auto-categorizes next time.
          </p>
          {ruleCreated ? (
            <p className="text-[var(--accent)]">
              Rule created. Manage it on the{' '}
              <Link className="underline" to="/settings/rules">
                Rules
              </Link>{' '}
              screen.
            </p>
          ) : (
            <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
                When payee contains
                <input
                  className="rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
                  value={pattern}
                  onChange={(e) => setPattern(e.target.value)}
                />
              </label>
              <label className="flex flex-col gap-1 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]">
                Categorize as
                <CategorySelect
                  emptyLabel="Choose…"
                  value={categoryId}
                  onChange={setCategoryId}
                />
              </label>
              <button
                type="button"
                disabled={!pattern.trim() || categoryId === null || createRule.isPending}
                onClick={() =>
                  createRule.mutate(
                    {
                      match_field: 'payee',
                      pattern: pattern.trim(),
                      category_id: categoryId as number,
                      priority: 0,
                    },
                    { onSuccess: () => setRuleCreated(true) },
                  )
                }
                className="rounded bg-[var(--accent)] px-3 py-1.5 text-[var(--accent-fg)] disabled:opacity-50"
              >
                Create rule
              </button>
            </div>
          )}
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={onReset}
          className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--fg)] hover:bg-[var(--row-hover)]"
        >
          Import another file
        </button>
        <Link
          to="/transactions"
          className="rounded border border-[var(--border-strong)] px-3 py-1.5 text-[var(--accent)] hover:bg-[var(--row-hover)]"
        >
          View transactions
        </Link>
      </div>
    </div>
  )
}

export function ImportPage() {
  const accounts = useAccounts()
  const previewMut = useImportPreview()
  const remapMut = useImportRemap()
  const commitMut = useImportCommit()

  const [step, setStep] = useState<Step>('upload')
  const [accountId, setAccountId] = useState<number | null>(null)
  const [preview, setPreview] = useState<ImportPreviewResponse | null>(null)
  const [mapping, setMapping] = useState<ImportMapping | null>(null)
  const [result, setResult] = useState<ImportCommitResponse | null>(null)
  const [committedRows, setCommittedRows] = useState<ImportCommitRow[]>([])

  const activeAccountId = accountId ?? accounts.data?.[0]?.id ?? null

  const reset = () => {
    setStep('upload')
    setPreview(null)
    setMapping(null)
    setResult(null)
    setCommittedRows([])
  }

  const handleFile = (file: File) => {
    if (activeAccountId === null) return
    previewMut.mutate(
      { file, accountId: activeAccountId },
      {
        onSuccess: (data) => {
          setPreview(data)
          setMapping(data.mapping)
          setStep('mapping')
        },
      },
    )
  }

  const error = previewMut.error ?? remapMut.error ?? commitMut.error

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div>
        <h1 className="text-lg font-semibold text-[var(--fg)]">Import CSV</h1>
        <p className="text-[var(--fg-muted)]">
          Preview a bank export, fix the mapping, review rows, then commit.
          Nothing is saved until you confirm.
        </p>
      </div>

      {error && (
        <ErrorState
          message={error instanceof ApiError ? error.detail : 'Import failed.'}
        />
      )}

      {step === 'upload' && (
        <div className="flex flex-col gap-3">
          <label className="flex items-center gap-2 text-[var(--fg-muted)]">
            Import into
            <select
              className="rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)]"
              value={activeAccountId ?? ''}
              onChange={(e) => setAccountId(Number(e.target.value))}
            >
              {(accounts.data ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <DropZone onFile={handleFile} />
          {previewMut.isPending && (
            <p className="text-[var(--fg-muted)]">Reading file…</p>
          )}
        </div>
      )}

      {step === 'mapping' && preview && mapping && (
        <MappingStep
          preview={preview}
          mapping={mapping}
          onChange={setMapping}
          onBack={() => setStep('upload')}
          busy={remapMut.isPending}
          onContinue={() =>
            remapMut.mutate(
              { token: preview.token, mapping },
              {
                onSuccess: (data) => {
                  setPreview(data)
                  setStep('review')
                },
              },
            )
          }
        />
      )}

      {step === 'review' && preview && (
        <ReviewTable
          preview={preview}
          committing={commitMut.isPending}
          onBack={() => setStep('mapping')}
          onCommit={(rows, skipDuplicates) => {
            commitMut.mutate(
              { token: preview.token, rows, skipDuplicates },
              {
                onSuccess: (data) => {
                  setResult(data)
                  setCommittedRows(rows)
                  setStep('done')
                },
              },
            )
          }}
        />
      )}

      {step === 'done' && result && (
        <ResultPanel
          result={result}
          committedRows={committedRows}
          onReset={reset}
        />
      )}
    </div>
  )
}

import { Link } from 'react-router-dom'

import { useAccounts, useCategories } from '../lib/queries'
import { ApiError } from '../lib/api'
import { ErrorState, SkeletonRows } from '../components/ui'

export function SettingsPage() {
  const accounts = useAccounts(true)
  const categories = useCategories(true)

  if (accounts.isLoading || categories.isLoading) {
    return (
      <div className="max-w-3xl">
        <SkeletonRows rows={6} />
      </div>
    )
  }
  if (accounts.isError || categories.isError) {
    const err = accounts.error ?? categories.error
    const message = err instanceof ApiError ? err.detail : 'Failed to load settings.'
    return <ErrorState message={message} />
  }

  const accountCount = accounts.data?.length ?? 0
  const groupCount = categories.data?.length ?? 0

  const card =
    'block rounded-md border border-[var(--border)] px-4 py-3 hover:bg-[var(--row-hover)]'

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-3">
      <h1 className="text-lg font-semibold text-[var(--fg)]">Settings</h1>
      <p className="text-[var(--fg-muted)]">
        {accountCount} account(s) · {groupCount} category group(s).
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Link to="/settings/import" className={card}>
          <p className="font-medium text-[var(--fg)]">Import CSV</p>
          <p className="text-[var(--fg-muted)]">
            Bring in bank exports with a preview-then-commit flow.
          </p>
        </Link>
        <Link to="/settings/rules" className={card}>
          <p className="font-medium text-[var(--fg)]">Rules</p>
          <p className="text-[var(--fg-muted)]">
            Auto-categorize transactions by payee or memo.
          </p>
        </Link>
      </div>
    </div>
  )
}

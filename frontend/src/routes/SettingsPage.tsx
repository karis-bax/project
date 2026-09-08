import { useAccounts, useCategories } from '../lib/queries'
import { ApiError } from '../lib/api'
import { EmptyState, ErrorState, Placeholder, SkeletonRows } from '../components/ui'

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
  if (accountCount === 0 && groupCount === 0) {
    return (
      <EmptyState
        title="Nothing to configure yet"
        hint="Add accounts and category groups to begin."
      />
    )
  }

  return (
    <div className="max-w-3xl">
      <Placeholder
        title="Settings editors arrive in a later phase"
        hint={`${accountCount} account(s) and ${groupCount} category group(s) connected from the live API.`}
      />
    </div>
  )
}

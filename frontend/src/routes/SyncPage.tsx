import { useState } from 'react'

import { ApiError } from '../lib/api'
import { formatCents } from '../lib/money'
import {
  useAccounts,
  useClaimSetupToken,
  useLinkSyncAccount,
  useRunSync,
  useSyncAccounts,
  useSyncRuns,
} from '../lib/queries'
import type { SyncAccountStatus, SyncRunRead } from '../lib/types'
import { EmptyState, ErrorState, Money, SkeletonRows } from '../components/ui'

function errText(entry: unknown): string {
  if (typeof entry === 'string') return entry
  if (entry && typeof entry === 'object' && 'message' in entry) {
    return String((entry as { message: unknown }).message)
  }
  return JSON.stringify(entry)
}

function ErrlistBanners({ runs }: { runs: SyncRunRead[] }) {
  const latest = runs[0]
  if (!latest || !latest.errors || latest.errors.length === 0) return null
  return (
    <div className="flex flex-col gap-2">
      {latest.errors.map((e, i) => (
        <div
          key={i}
          className="rounded-md border border-[var(--warn)] bg-[var(--warn-weak)] px-3 py-2 text-[var(--warn)]"
        >
          <span className="font-medium">Action needed: </span>
          {errText(e)}
        </div>
      ))}
    </div>
  )
}

function ConnectScreen() {
  const claim = useClaimSetupToken()
  const [token, setToken] = useState('')

  return (
    <div className="flex flex-col gap-3">
      <EmptyState
        title="Connect your bank"
        hint="Paste a SimpleFIN Bridge setup token to discover your accounts. Setup tokens are one-time."
      />
      <textarea
        className="min-h-24 rounded-md border border-[var(--border)] bg-[var(--panel-raised)] p-3 font-mono text-[var(--fg)] focus:border-[var(--accent)] focus:outline-none"
        placeholder="Paste your SimpleFIN setup token here…"
        value={token}
        onChange={(e) => setToken(e.target.value)}
      />
      {claim.isError && (
        <ErrorState
          message={
            claim.error instanceof ApiError ? claim.error.detail : 'Could not connect.'
          }
        />
      )}
      <div>
        <button
          type="button"
          disabled={!token.trim() || claim.isPending}
          onClick={() => claim.mutate(token.trim())}
          className="rounded bg-[var(--accent)] px-4 py-1.5 text-[var(--accent-fg)] disabled:opacity-50"
        >
          {claim.isPending ? 'Connecting…' : 'Connect'}
        </button>
      </div>
    </div>
  )
}

function AccountRow({ row }: { row: SyncAccountStatus }) {
  const accounts = useAccounts()
  const link = useLinkSyncAccount()
  const [creating, setCreating] = useState(false)
  const [newName, setNewName] = useState(row.name)

  const linked = row.linked_account_id !== null

  return (
    <div className="grid items-center gap-2 border-b border-[var(--border)] px-3 py-2 last:border-b-0" style={{ gridTemplateColumns: '1.4fr 1.4fr 1fr 1fr 1fr' }}>
      <div className="min-w-0">
        <p className="truncate text-[var(--fg)]">{row.name}</p>
        <p className="truncate text-[11px] text-[var(--fg-subtle)]">{row.org_name}</p>
      </div>

      {linked ? (
        <span className="text-[var(--fg-muted)]">{row.local_account_name}</span>
      ) : creating ? (
        <div className="flex items-center gap-1">
          <input
            className="w-full rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)]"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <button
            type="button"
            className="rounded bg-[var(--accent)] px-2 py-1 text-[var(--accent-fg)]"
            onClick={() =>
              link.mutate({
                external_id: row.external_id,
                create_as: { name: newName.trim() || row.name, kind: 'checking' },
              })
            }
          >
            Create
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-1">
          <select
            className="w-full rounded border border-[var(--border)] bg-[var(--panel-raised)] px-2 py-1 text-[var(--fg)]"
            defaultValue=""
            onChange={(e) => {
              if (e.target.value) {
                link.mutate({
                  external_id: row.external_id,
                  account_id: Number(e.target.value),
                })
              }
            }}
          >
            <option value="">Link to…</option>
            {(accounts.data ?? []).map((a) => (
              <option key={a.id} value={a.id}>
                {a.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="whitespace-nowrap rounded border border-[var(--border-strong)] px-2 py-1 text-[var(--fg-muted)] hover:bg-[var(--row-hover)]"
            onClick={() => setCreating(true)}
          >
            New
          </button>
        </div>
      )}

      {/* Reconciliation: reported vs computed, side by side. */}
      <span className="num text-right tabular-nums text-[var(--fg)]">
        {row.reported_balance_cents === null ? '—' : formatCents(row.reported_balance_cents)}
      </span>
      <span className="num text-right tabular-nums">
        {row.computed_balance_cents === null ? (
          <span className="text-[var(--fg-subtle)]">—</span>
        ) : (
          <Money cents={row.computed_balance_cents} />
        )}
      </span>
      <span className="flex flex-col items-end text-[12px]">
        {row.mismatch ? (
          <span className="rounded bg-[var(--warn-weak)] px-1.5 py-0.5 text-[var(--warn)]">
            mismatch
          </span>
        ) : linked && row.reported_balance_cents !== null ? (
          <span className="text-[var(--accent)]">reconciled</span>
        ) : (
          <span className="text-[var(--fg-subtle)]">
            {row.last_synced_at ? '' : 'never synced'}
          </span>
        )}
        {row.opening_balance_source === 'derived_at_link' && (
          <span className="text-[var(--fg-subtle)]">anchored at link</span>
        )}
      </span>
    </div>
  )
}

export function SyncPage() {
  const syncAccounts = useSyncAccounts()
  const runs = useSyncRuns()
  const runSync = useRunSync()

  if (syncAccounts.isLoading) {
    return (
      <div className="mx-auto max-w-4xl">
        <SkeletonRows rows={6} />
      </div>
    )
  }
  if (syncAccounts.isError) {
    return (
      <ErrorState
        message={
          syncAccounts.error instanceof ApiError
            ? syncAccounts.error.detail
            : 'Failed to load sync status.'
        }
      />
    )
  }

  const rows = syncAccounts.data ?? []
  const connected = rows.length > 0

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-[var(--fg)]">Bank sync</h1>
          <p className="text-[var(--fg-muted)]">
            Live balances via SimpleFIN Bridge. Reconcile each account against
            your own ledger.
          </p>
        </div>
        {connected && (
          <button
            type="button"
            onClick={() => runSync.mutate(30)}
            disabled={runSync.isPending}
            className="rounded bg-[var(--accent)] px-4 py-1.5 text-[var(--accent-fg)] disabled:opacity-50"
          >
            {runSync.isPending ? 'Syncing…' : 'Sync now'}
          </button>
        )}
      </div>

      <ErrlistBanners runs={runs.data ?? []} />

      {runSync.data && (
        <div className="rounded-md border border-[var(--border)] bg-[var(--panel)] px-3 py-2">
          <span className="num tabular-nums text-[var(--fg)]">
            Last sync: {runSync.data.added} added · {runSync.data.updated} updated
            · {runSync.data.errors.length} errors
          </span>
        </div>
      )}

      {!connected ? (
        <ConnectScreen />
      ) : (
        <div className="rounded-md border border-[var(--border)]">
          <div
            className="grid gap-2 border-b border-[var(--border)] bg-[var(--panel)] px-3 py-2 text-[11px] uppercase tracking-wide text-[var(--fg-subtle)]"
            style={{ gridTemplateColumns: '1.4fr 1.4fr 1fr 1fr 1fr' }}
          >
            <span>SimpleFIN account</span>
            <span>Envelope account</span>
            <span className="text-right">Bank balance</span>
            <span className="text-right">Ledger balance</span>
            <span className="text-right">Status</span>
          </div>
          {rows.map((row) => (
            <AccountRow key={row.external_id} row={row} />
          ))}
        </div>
      )}

      {connected && (
        <p className="text-[12px] text-[var(--fg-subtle)]">
          Ledger balances are anchored to the bank's reported balance at link
          time — not a verified check of full history. After the anchor, any
          divergence between the two columns is real signal.
        </p>
      )}
    </div>
  )
}

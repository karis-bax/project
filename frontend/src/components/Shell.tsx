import { NavLink, Outlet, useLocation, useMatch } from 'react-router-dom'

import { currentMonth, formatMonthLabel } from '../lib/month'
import { useAccounts } from '../lib/queries'
import type { AccountKind, AccountRead } from '../lib/types'
import { EmptyState, Money, SkeletonRows } from './ui'

const KIND_LABEL: Record<AccountKind, string> = {
  checking: 'Checking',
  savings: 'Savings',
  credit: 'Credit',
  cash: 'Cash',
}

function navClass({ isActive }: { isActive: boolean }): string {
  const base =
    'block rounded px-2.5 py-1.5 text-[13px] transition-colors'
  return isActive
    ? `${base} bg-[var(--accent-weak)] text-[var(--accent)] font-medium`
    : `${base} text-[var(--fg-muted)] hover:bg-[var(--row-hover)] hover:text-[var(--fg)]`
}

function AccountBalances() {
  const { data, isLoading, isError } = useAccounts()

  if (isLoading) {
    return <SkeletonRows rows={3} className="px-1" />
  }
  if (isError || !data) {
    return (
      <p className="px-1 text-[var(--fg-subtle)]">Balances unavailable.</p>
    )
  }
  if (data.length === 0) {
    return (
      <div className="px-1">
        <EmptyState title="No accounts yet" hint="Add an account in Settings." />
      </div>
    )
  }

  // Until a computed-balance endpoint exists, show each account's opening
  // balance from the live API — enough to prove the sidebar is data-driven.
  const total = data.reduce(
    (sum: number, a: AccountRead) => sum + a.opening_balance_cents,
    0,
  )

  return (
    <ul className="flex flex-col">
      {data.map((account) => (
        <li
          key={account.id}
          className="flex items-baseline justify-between gap-3 py-1"
        >
          <span className="min-w-0 truncate">
            <span className="text-[var(--fg)]">{account.name}</span>
            <span className="ml-1.5 text-[var(--fg-subtle)]">
              {KIND_LABEL[account.kind]}
            </span>
          </span>
          <Money cents={account.opening_balance_cents} className="shrink-0" />
        </li>
      ))}
      <li className="mt-1.5 flex items-baseline justify-between gap-3 border-t border-[var(--border)] pt-1.5">
        <span className="text-[var(--fg-muted)]">Total</span>
        <Money cents={total} className="shrink-0 font-medium" />
      </li>
    </ul>
  )
}

export function Shell() {
  const location = useLocation()
  const budgetMatch = useMatch('/budget/:month')
  const month = budgetMatch?.params.month

  const budgetActive = location.pathname.startsWith('/budget')

  return (
    <div className="flex h-full bg-[var(--bg)] text-[var(--fg)]">
      <aside className="flex w-60 shrink-0 flex-col border-r border-[var(--border)] bg-[var(--panel)]">
        <div className="flex items-center gap-2 px-4 py-3.5 border-b border-[var(--border)]">
          <span className="grid h-6 w-6 place-items-center rounded bg-[var(--accent)] text-[var(--accent-fg)] text-[13px] font-semibold">
            E
          </span>
          <span className="font-semibold tracking-tight">Envelope</span>
        </div>

        <nav className="flex flex-col gap-0.5 p-2">
          <NavLink
            to={`/budget/${currentMonth()}`}
            className={() => navClass({ isActive: budgetActive })}
          >
            Budget
          </NavLink>
          <NavLink to="/transactions" className={navClass}>
            Transactions
          </NavLink>
          <NavLink to="/insights" className={navClass}>
            Insights
          </NavLink>
          <NavLink to="/settings" className={navClass}>
            Settings
          </NavLink>
        </nav>

        <div className="mt-2 px-3">
          <p className="px-1 pb-1 text-[11px] font-medium uppercase tracking-wide text-[var(--fg-subtle)]">
            Accounts
          </p>
          <AccountBalances />
        </div>

        <div className="mt-auto px-4 py-3 text-[11px] text-[var(--fg-subtle)] border-t border-[var(--border)]">
          Zero-based budgeting
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--border)] bg-[var(--panel)] px-5">
          <span className="font-medium capitalize text-[var(--fg)]">
            {month ? formatMonthLabel(month) : location.pathname.replace('/', '') || 'Budget'}
          </span>
        </header>

        <main className="min-h-0 flex-1 overflow-auto px-5 py-5">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

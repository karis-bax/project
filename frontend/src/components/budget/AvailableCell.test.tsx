// @vitest-environment jsdom
import { cleanup, render, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it } from 'vitest'

import type { CategoryBudgetRow } from '../../lib/types'
import { AvailableCell } from './AvailableCell'

afterEach(cleanup)

function row(overrides: Partial<CategoryBudgetRow> = {}): CategoryBudgetRow {
  return {
    id: 1,
    name: 'Groceries',
    assigned_cents: 0,
    activity_cents: 0,
    available_cents: 0,
    pending_cents: 0,
    ...overrides,
  }
}

function renderCell(category: CategoryBudgetRow) {
  return render(
    <MemoryRouter>
      <AvailableCell category={category} goal={undefined} month="2026-05" />
    </MemoryRouter>,
  )
}

function srSentence(container: HTMLElement): string {
  return container.querySelector('.sr-only')?.textContent ?? ''
}

function linkText(container: HTMLElement): string | null {
  return within(container).queryByRole('link')?.textContent ?? null
}

describe('AvailableCell', () => {
  it('renders no pending line at pending 0 but reserves the row height', () => {
    const { container } = renderCell(row({ available_cents: 12700 }))
    const slot = container.querySelector('[data-testid="pending-slot"]')
    expect(slot).not.toBeNull()
    expect(within(slot as HTMLElement).queryByRole('link')).toBeNull()
    expect(slot?.textContent).toBe('')

    // The same reserved slot exists when pending is present -> equal height.
    const withPending = renderCell(row({ available_cents: 12700, pending_cents: -4300 }))
    const slot2 = withPending.container.querySelector('[data-testid="pending-slot"]')
    expect(slot2).not.toBeNull()
    expect((slot as HTMLElement).className).toBe((slot2 as HTMLElement).className)
  })

  it('renders a pending outflow as a positive magnitude with "pending"', () => {
    const { container } = renderCell(row({ available_cents: 12000, pending_cents: -4300 }))
    const text = linkText(container)
    expect(text).toBe('$43.00 pending')
    expect(text).not.toContain('-')
  })

  it('renders a pending inflow distinctly from an outflow', () => {
    const { container } = renderCell(row({ available_cents: 12000, pending_cents: 50000 }))
    expect(linkText(container)).toBe('+$500.00 pending')
  })

  it('covered state: available 12000, pending 4300 -> no shortfall', () => {
    const { container } = renderCell(row({ available_cents: 12000, pending_cents: -4300 }))
    expect(linkText(container)).not.toContain('short')
  })

  it('short state: available 3100, pending 4300 -> correct shortfall', () => {
    const { container } = renderCell(row({ available_cents: 3100, pending_cents: -4300 }))
    expect(linkText(container)).toBe('$43.00 pending · $12.00 short')
  })

  it('produces an aria-label sentence for each of the three states', () => {
    expect(srSentence(renderCell(row({ available_cents: 12700 })).container)).toBe(
      'Available $127.00',
    )
    expect(
      srSentence(
        renderCell(row({ available_cents: 12000, pending_cents: -4300 })).container,
      ),
    ).toBe('Available $120.00, $43.00 pending')
    expect(
      srSentence(
        renderCell(row({ available_cents: 3100, pending_cents: -4300 })).container,
      ),
    ).toBe('Available $31.00, $43.00 pending, $12.00 short once pending clears')
  })

  it('updates the figure on refetch (re-render with new props)', () => {
    const { container, rerender } = renderCell(
      row({ available_cents: 12000, pending_cents: -4300 }),
    )
    expect(linkText(container)).toBe('$43.00 pending')
    rerender(
      <MemoryRouter>
        <AvailableCell
          category={row({ available_cents: 12000, pending_cents: -5000 })}
          goal={undefined}
          month="2026-05"
        />
      </MemoryRouter>,
    )
    expect(linkText(container)).toBe('$50.00 pending')
  })
})

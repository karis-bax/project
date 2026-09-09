import { describe, expect, it } from 'vitest'

import { neighborId } from './gridNav'

describe('neighborId (grid keyboard navigation / trap avoidance)', () => {
  const ids = [10, 20, 30]

  it('returns the next id in the middle of the grid', () => {
    expect(neighborId(ids, 20, 1)).toBe(30)
    expect(neighborId(ids, 20, -1)).toBe(10)
  })

  it('returns undefined past the last cell (Tab must leave the grid)', () => {
    expect(neighborId(ids, 30, 1)).toBeUndefined()
  })

  it('returns undefined before the first cell (Shift+Tab must leave)', () => {
    expect(neighborId(ids, 10, -1)).toBeUndefined()
  })

  it('returns undefined for an unknown id', () => {
    expect(neighborId(ids, 999, 1)).toBeUndefined()
  })
})

import { describe, expect, it } from 'vitest'

import {
  formatCents,
  formatCentsForInput,
  parseAmountInput,
  parseDollars,
} from './money'

describe('parseDollars', () => {
  it('parses plain integers', () => {
    expect(parseDollars('12')).toBe(1200)
  })

  it('parses one decimal place', () => {
    expect(parseDollars('12.5')).toBe(1250)
  })

  it('parses currency formatting with $ and commas', () => {
    expect(parseDollars('$1,234.56')).toBe(123456)
  })

  it('parses negatives', () => {
    expect(parseDollars('-40')).toBe(-4000)
    expect(parseDollars('-$12.34')).toBe(-1234)
  })

  it('handles two decimal places exactly', () => {
    expect(parseDollars('0.99')).toBe(99)
    expect(parseDollars('100.00')).toBe(10000)
  })

  describe('rounding edge cases (decimal half-up on the third digit)', () => {
    it('rounds half up', () => {
      expect(parseDollars('12.555')).toBe(1256)
      expect(parseDollars('12.005')).toBe(1201)
    })

    it('rounds down below half', () => {
      expect(parseDollars('12.004')).toBe(1200)
      expect(parseDollars('12.994')).toBe(1299)
    })

    it('carries into the next dollar', () => {
      expect(parseDollars('0.999')).toBe(100)
      expect(parseDollars('12.999')).toBe(1300)
    })

    it('applies half-up away from zero for negatives', () => {
      expect(parseDollars('-12.005')).toBe(-1201)
    })

    it('is not fooled by binary floating point', () => {
      // 0.1 + 0.2 style inputs that naive `Math.round(n * 100)` gets wrong.
      expect(parseDollars('1.005')).toBe(101)
      expect(parseDollars('2.675')).toBe(268)
    })
  })

  it('throws on non-numeric input', () => {
    expect(() => parseDollars('abc')).toThrow()
    expect(() => parseDollars('')).toThrow()
    expect(() => parseDollars('$')).toThrow()
  })

  it('rejects integer parts beyond 15 digits rather than losing precision', () => {
    expect(() => parseDollars('9999999999999999')).toThrow(/too large/)
    // 15 digits is still accepted.
    expect(parseDollars('999999999999999')).toBe(99999999999999900)
  })
})

describe('formatCents', () => {
  it('formats positive and negative amounts', () => {
    expect(formatCents(123456)).toBe('$1,234.56')
    expect(formatCents(-4000)).toBe('-$40.00')
    expect(formatCents(0)).toBe('$0.00')
  })

  it('adds an explicit sign when requested', () => {
    expect(formatCents(1250, { sign: true })).toBe('+$12.50')
    expect(formatCents(-4000, { sign: true })).toBe('-$40.00')
    expect(formatCents(0, { sign: true })).toBe('$0.00')
  })
})

describe('formatCentsForInput', () => {
  it('renders whole dollars without decimals', () => {
    expect(formatCentsForInput(2150000)).toBe('21500')
    expect(formatCentsForInput(0)).toBe('0')
  })

  it('renders fractional and sub-dollar amounts with two digits', () => {
    expect(formatCentsForInput(2150)).toBe('21.50')
    expect(formatCentsForInput(5)).toBe('0.05')
    expect(formatCentsForInput(60)).toBe('0.60')
  })

  it('handles negatives', () => {
    expect(formatCentsForInput(-4000)).toBe('-40')
    expect(formatCentsForInput(-5)).toBe('-0.05')
    expect(formatCentsForInput(-12345)).toBe('-123.45')
  })

  it('round-trips through parseDollars', () => {
    for (const c of [0, 5, -5, 60, 2150, -12345, 2150000]) {
      expect(parseDollars(formatCentsForInput(c))).toBe(c)
    }
  })
})

describe('parseAmountInput', () => {
  it('defaults to an outflow (negative)', () => {
    expect(parseAmountInput('12.50')).toBe(-1250)
    expect(parseAmountInput('40')).toBe(-4000)
    expect(parseAmountInput('1,234.56')).toBe(-123456)
  })

  it('treats a leading + as income (positive)', () => {
    expect(parseAmountInput('+40')).toBe(4000)
    expect(parseAmountInput('+1,234.56')).toBe(123456)
  })

  it('respects an explicit leading -', () => {
    expect(parseAmountInput('-40')).toBe(-4000)
  })

  it('throws on invalid input', () => {
    expect(() => parseAmountInput('')).toThrow()
    expect(() => parseAmountInput('+')).toThrow()
  })
})

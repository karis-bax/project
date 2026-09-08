/**
 * Money helpers. All amounts in the app are signed integer cents; formatting to
 * dollars happens only here (in render code).
 */

const USD = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
})

const USD_SIGNED = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  signDisplay: 'exceptZero',
})

/**
 * Format integer cents as USD. With `{ sign: true }`, positive amounts get an
 * explicit `+` (zero stays unsigned).
 */
export function formatCents(n: number, opts?: { sign?: boolean }): string {
  const dollars = n / 100
  return (opts?.sign ? USD_SIGNED : USD).format(dollars)
}

/**
 * Parse a user-entered dollar string into signed integer cents.
 *
 * Accepts values like "12", "12.5", "$1,234.56", "-40". Rounding is decimal
 * half-up on the third fractional digit (computed from the string, not via
 * float math, so "12.005" -> 1201 and "12.555" -> 1256 deterministically).
 * Throws on input that is not a number.
 */
export function parseDollars(input: string): number {
  const cleaned = input.replace(/[$,\s]/g, '')
  if (!/^-?\d+(\.\d*)?$/.test(cleaned)) {
    throw new Error(`Not a valid dollar amount: ${JSON.stringify(input)}`)
  }

  const negative = cleaned.startsWith('-')
  const unsigned = negative ? cleaned.slice(1) : cleaned
  const [whole, frac = ''] = unsigned.split('.')

  const wholeCents = Number(whole) * 100

  let fracCents = 0
  if (frac.length > 0) {
    fracCents = Number(frac.slice(0, 2).padEnd(2, '0'))
    // Half-up rounding using the third fractional digit.
    if (frac.length > 2 && Number(frac[2]) >= 5) {
      fracCents += 1
    }
  }

  const total = wholeCents + fracCents
  return negative ? -total : total
}

/**
 * Money formatting. Mirrors frontend/src/lib/money.ts.
 *
 * Money arrives from the API as signed integer cents and stays that way through
 * every calculation. These helpers are the ONLY place cents become a string,
 * and they use integer arithmetic to get there — no `cents / 100`.
 */

/** "$1,234.56" — or "-$12.00" for an outflow. */
export function formatCents(cents: number, opts: { sign?: boolean } = {}): string {
  const negative = cents < 0
  const abs = Math.abs(cents)
  const whole = Math.trunc(abs / 100)
  const frac = abs % 100
  const grouped = whole.toLocaleString('en-US')
  const body = `$${grouped}.${String(frac).padStart(2, '0')}`
  if (negative) return `-${body}`
  return opts.sign ? `+${body}` : body
}

/** "$1,234" — for tight spaces where cents are noise. */
export function formatCentsShort(cents: number): string {
  const negative = cents < 0
  const whole = Math.trunc(Math.abs(cents) / 100)
  return `${negative ? '-' : ''}$${whole.toLocaleString('en-US')}`
}

/**
 * Parse a typed dollar amount into integer cents.
 *
 * Accepts "12", "12.5", "$1,234.56", "-40", "+500". Returns null for anything
 * it cannot parse, so callers surface a validation message rather than writing
 * NaN into the ledger.
 *
 * The integer part is length-checked rather than multiplied blindly: beyond 15
 * digits `Number * 100` silently loses precision.
 */
export function parseDollars(input: string): number | null {
  const trimmed = input.trim().replace(/[$,\s]/g, '')
  if (!trimmed) return null
  const match = /^([+-]?)(\d*)(?:\.(\d{0,2}))?$/.exec(trimmed)
  if (!match) return null
  const [, signPart, wholePart, fracPart] = match
  if (!wholePart && !fracPart) return null
  if (wholePart.length > 15) return null
  const whole = wholePart ? parseInt(wholePart, 10) : 0
  const frac = fracPart ? parseInt(fracPart.padEnd(2, '0'), 10) : 0
  const magnitude = whole * 100 + frac
  return signPart === '-' ? -magnitude : magnitude
}

/** Helpers for `YYYY-MM` budget-month strings. */

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/

export function isValidMonth(month: string): boolean {
  return MONTH_RE.test(month)
}

export function currentMonth(now: Date = new Date()): string {
  const year = now.getFullYear()
  const month = `${now.getMonth() + 1}`.padStart(2, '0')
  return `${year}-${month}`
}

export function addMonths(month: string, delta: number): string {
  const year = Number(month.slice(0, 4))
  const monthIndex = Number(month.slice(5, 7)) - 1
  const date = new Date(year, monthIndex + delta, 1)
  const nextYear = date.getFullYear()
  const nextMonth = `${date.getMonth() + 1}`.padStart(2, '0')
  return `${nextYear}-${nextMonth}`
}

const MONTH_LABEL = new Intl.DateTimeFormat('en-US', {
  month: 'long',
  year: 'numeric',
})

export function formatMonthLabel(month: string): string {
  if (!isValidMonth(month)) return month
  const year = Number(month.slice(0, 4))
  const monthIndex = Number(month.slice(5, 7)) - 1
  return MONTH_LABEL.format(new Date(year, monthIndex, 1))
}

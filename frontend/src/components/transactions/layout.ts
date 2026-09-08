/** Shared grid column template so the header, quick-add, and rows stay aligned:
 * date | payee | category | memo | amount | cleared */
export const REGISTER_COLS =
  '7rem minmax(8rem,1.4fr) 12rem minmax(6rem,1fr) 8.5rem 4rem'

export function todayISO(): string {
  const d = new Date()
  const month = `${d.getMonth() + 1}`.padStart(2, '0')
  const day = `${d.getDate()}`.padStart(2, '0')
  return `${d.getFullYear()}-${month}-${day}`
}

const SHORT_DATE = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
})

/** Format an ISO YYYY-MM-DD date as e.g. "Aug 15" (parsed as a local date). */
export function formatShortDate(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  if (!year || !month || !day) return iso
  return SHORT_DATE.format(new Date(year, month - 1, day))
}

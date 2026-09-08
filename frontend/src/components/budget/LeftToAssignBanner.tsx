import { formatCents } from '../../lib/money'

/**
 * "Left to assign" banner. Three visually distinct states, using semantic status
 * colors kept separate from the app accent:
 *  - positive: money is still waiting to be assigned (info)
 *  - zero:     the goal state — calm, every dollar has a job (calm)
 *  - negative: over-assigned, needs attention (warn)
 */
export function LeftToAssignBanner({ cents }: { cents: number }) {
  const state = cents > 0 ? 'positive' : cents < 0 ? 'negative' : 'zero'

  const styles = {
    positive: {
      box: 'border-[var(--info)] bg-[var(--info-weak)]',
      figure: 'text-[var(--info)]',
      caption: 'Left to assign',
    },
    zero: {
      box: 'border-[var(--calm)] bg-[var(--calm-weak)]',
      figure: 'text-[var(--calm)]',
      caption: 'Every dollar has a job',
    },
    negative: {
      box: 'border-[var(--warn)] bg-[var(--warn-weak)]',
      figure: 'text-[var(--warn)]',
      caption: 'Over-assigned — needs attention',
    },
  }[state]

  return (
    <section
      aria-live="polite"
      className={`flex items-baseline justify-between gap-4 rounded-md border border-l-4 px-4 py-3 ${styles.box}`}
    >
      <div className="flex flex-col">
        <span className="text-[11px] uppercase tracking-wide text-[var(--fg-muted)]">
          {styles.caption}
        </span>
        <span className={`num text-3xl font-semibold tabular-nums ${styles.figure}`}>
          {formatCents(cents)}
        </span>
      </div>
      {state === 'zero' && (
        <span className="text-[var(--calm)]" aria-hidden>
          ✓
        </span>
      )}
    </section>
  )
}

# Envelope

Zero-based personal budgeting app. Every dollar is assigned to a category
envelope; overspending carries forward rather than resetting at the month
boundary.

## Where this is going
- FastAPI backend, deployed to an always-on host (not a laptop).
- Expo / React Native phone client — the primary interface. Capture-first:
  quick transaction entry, receipt camera, category balances at a glance.
- The existing Vite/React web app is the DESKTOP half: the envelope grid,
  monthly assignment, multi-month planning. Keep it; don't port it to mobile.
- Auth is required before the API is reachable from anything but localhost.

## Layout
- `backend/` — FastAPI, SQLAlchemy 2.0 declarative (SYNC, not async),
  Pydantic v2, Alembic. Dependencies via `uv`.
- Database: SQLite today; Postgres when this moves to a host.
- `frontend/` — Vite + React 18 + TypeScript strict, TanStack Query v5,
  React Router v6, Tailwind v4 (CSS-first, no tailwind.config.js), Recharts.

## Dev commands
- `just dev` runs backend on :8000 and frontend on :5173. `just --list` for
  the rest (test, migrate, seed, backup, restore-drill, purge).
- First checkout: `cd backend && uv sync`, then `cd frontend && npm install`.
- Add backend dependencies with `uv add <pkg>`; run backend commands with
  `uv run`.

## Money — the rule that outranks everything
- Money is ALWAYS signed integer cents, named `amount_cents`. Never a float,
  never a Decimal in storage, never a string.
- Outflows negative, inflows positive.
- Dollar formatting happens only in render code, via the `formatCents` /
  `formatCentsForInput` helpers in `frontend/src/lib/money.ts`.
- Any external source that sends decimal strings (SimpleFIN sends "-33.45")
  is parsed with `decimal.Decimal` and quantized to cents. Never `float()`.

## Budget semantics
- `available` = previous month's available + assigned + activity. A negative
  available carries forward as negative. Do not reset overspending to zero.
- PENDING TRANSACTIONS ARE EXCLUDED from activity, available, income and
  left_to_assign. A pending authorization is not settled money. It surfaces
  as a separate `pending_cents` figure, never folded into a total.
- Dates are ISO `YYYY-MM-DD`. Budget months are `YYYY-MM`.

## API
- Every route prefixed `/api` and returns a Pydantic response model, never a
  raw dict.
- Malformed input is 4xx, never 500.
- No N+1 queries. `month_view` is a constant query count regardless of
  category count.

## Bank sync (SimpleFIN)
- The access URL is a read key to the full financial history. It lives in the
  OS keyring or an env var — never the database, never a config file, never a
  log line, never a test fixture.
- Never call the SimpleFIN claim endpoint from tests. Setup tokens are
  one-time and burning one costs a manual regeneration.
- Posted-transaction dedup uses count matching on a content key, not a unique
  content hash — two genuine identical same-day charges must both survive.
- Sync owns amount, date, description and pending status. The user owns
  category and memo. Resync never overwrites a category.

## Soft-delete
- Transactions soft-delete via `deleted_at`. Filtering is enforced at session
  level with `with_loader_criteria` — never add `.where(deleted_at.is_(None))`
  by hand.
- A matching insert against a soft-deleted row REVIVES it rather than
  inserting a duplicate or being skipped as seen.

## Conventions
- No `any` in TypeScript. No bare `except:` in Python.
- Components over ~200 lines get split when a feature takes you into them —
  not as standalone refactor work.

# Envelope

A zero-based personal budgeting app. Every dollar gets a job: assign income to
budget categories ("envelopes") until nothing is left unassigned.

- **Backend** (`backend/`): Python 3.12, FastAPI, SQLAlchemy 2.0 (sync),
  Pydantic v2, Alembic, SQLite — dependencies managed with [`uv`].
- **Frontend** (`frontend/`): Vite + React 18 + TypeScript (strict), TanStack
  Query v5, React Router v6, Tailwind CSS v4, Recharts.

Money is always stored and transported as **signed integer cents**
(`amount_cents`): outflows negative, inflows positive. Dollar formatting happens
only in the React UI. See [`.cursor/rules/stack.mdc`](.cursor/rules/stack.mdc)
for the full conventions that govern this repo.

> **Status:** scaffolding only. Application code (backend app, frontend app,
> migrations, seed script) is not implemented yet, so the run commands below
> describe the intended workflow once those pieces land.

## Run it

Prerequisites:

- [`uv`](https://docs.astral.sh/uv/) (Python 3.12 toolchain + dependency manager)
- [Node.js](https://nodejs.org/) 20+ and npm
- [`just`](https://github.com/casey/just) (task runner)

Install dependencies:

```bash
cd backend && uv sync && cd ..
cd frontend && npm install && cd ..
```

Set up the database and start everything:

```bash
just migrate   # apply Alembic migrations
just seed      # load sample data (optional)
just dev       # run the API on :8000 and the frontend on :5173
```

Then open http://localhost:5173. The API is served under http://localhost:8000/api.

## Tasks

| Command        | What it does                                              |
| -------------- | -------------------------------------------------------- |
| `just dev`     | Run the FastAPI backend (`:8000`) and Vite frontend (`:5173`). |
| `just test`    | Run the backend test suite (`uv run pytest -q`).          |
| `just migrate` | Apply database migrations (`uv run alembic upgrade head`).|
| `just seed`    | Seed the database with sample data.                       |

## Layout

```
.
├── backend/                 # FastAPI app (to be added)
├── frontend/                # Vite + React app (to be added)
├── .cursor/
│   ├── environment.json     # Cloud Agent dev environment
│   └── rules/
│       ├── stack.mdc        # Stack, money, date, and API conventions (always on)
│       └── testing.mdc      # Backend testing rules (backend/**/*.py)
├── justfile                 # dev / test / migrate / seed
└── README.md
```

[`uv`]: https://docs.astral.sh/uv/

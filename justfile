# Envelope task runner. Run `just` or `just --list` to see targets.

# Run the backend (port 8000) and frontend (port 5173) together.
dev:
    cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload & \
    cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

# Run the backend test suite.
test:
    cd backend && uv run pytest -q

# Apply database migrations.
migrate:
    cd backend && uv run alembic upgrade head

# Seed the database with sample data.
seed:
    cd backend && uv run python -m app.seed

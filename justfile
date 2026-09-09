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

# Create an encrypted, off-host-decryptable database backup.
backup:
    cd backend && uv run python scripts/backup.py

# Prove the latest backup restores (integrity + row-count comparison).
restore-drill:
    cd backend && uv run python scripts/restore_drill.py

# Hard-delete transactions soft-deleted more than 90 days ago.
purge:
    cd backend && uv run python scripts/purge_soft_deleted.py

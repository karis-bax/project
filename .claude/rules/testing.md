---
paths:
  - "backend/**/*.py"
---

# Backend testing

- pytest + FastAPI TestClient. Each test gets a fresh in-memory SQLite via
  fixture: `sqlite://` with a `StaticPool`, wired in by overriding the app's DB
  dependency so tests never touch a real `.db` file.
- Every new endpoint ships with at least one happy-path and one failure test.
- Run `uv run pytest -q` from `backend/` before calling any backend task done,
  and paste the output rather than asserting it passed.
- Never call the SimpleFIN claim endpoint from a test.
- Money assertions use exact integer cents. A test that rounds is a broken test.

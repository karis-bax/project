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
- A new route must be added to the spec table in
  `tests/test_cross_user_isolation.py` with at least one probe, or classified
  PUBLIC/EXEMPT. The guard fails on an unclassified route in both directions.
- Isolation tests use `client_as` (a real login over HTTP), never the
  `client` fixture's dependency override. A test that proves separation while
  bypassing the mechanism enforcing it proves nothing.

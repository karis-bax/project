"""Shared test fixtures.

Previously every DB-using test module hand-rolled the same in-memory engine,
under two different names (``session`` in test_api/test_soft_delete, ``db`` in
test_budget/test_sync). They are consolidated here; ``session`` is an alias
fixture depending on ``db``, so both names resolve to the *same* Session object
and no existing test body needed rewriting.

Two kinds of authenticated client:

- ``client`` overrides the auth dependency. Fast, and keeps the ~76 pre-auth
  tests working unchanged.
- ``client_as(user)`` performs a REAL login over HTTP and sends a real bearer
  token. The isolation tests use this one, because a test that proves
  separation while bypassing the thing that enforces it proves nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.dependencies import current_user_optional, get_auth_db
from app.auth.security import hash_password
from app.db import TENANT, Base
from app.deps import get_db
from app.main import app
from app.models import User

DEFAULT_PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    """A fresh in-memory SQLite database per test.

    StaticPool + check_same_thread=False keeps one connection shared with the
    TestClient's threadpool, so test-side writes are visible to request-side
    reads.
    """

    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(eng)

    # Rebind the app's session factory to this engine, in every module that
    # imported it by name. This is what lets the REAL get_db run in tests —
    # including its tenant binding — instead of being replaced by an override
    # that would quietly skip the thing under test.
    factory = sessionmaker(
        bind=eng, autoflush=False, autocommit=False,
        expire_on_commit=False, class_=Session,
    )
    for target in ("app.db", "app.deps", "app.auth.dependencies"):
        monkeypatch.setattr(f"{target}.SessionLocal", factory, raising=False)

    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def make_user(engine: Engine) -> Callable[..., User]:
    """Create a user directly, outside tenant scoping (users are not owned)."""

    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def _make(email: str, password: str = DEFAULT_PASSWORD) -> User:
        with factory() as s:
            user = User(email=email, password_hash=hash_password(password))
            s.add(user)
            s.commit()
            s.refresh(user)
            return user

    return _make


@pytest.fixture
def default_user(make_user: Callable[..., User]) -> User:
    """The user that legacy tests implicitly run as."""

    return make_user("owner@example.com")


@pytest.fixture
def db(engine: Engine, default_user: User) -> Iterator[Session]:
    """The canonical session fixture, scoped to ``default_user``.

    ``info[TENANT]`` is what lets direct ORM writes in test helpers
    (``seed_basics``, ``make_account``, ...) get their ``user_id`` stamped by
    the before_flush listener, so those helpers needed no changes.
    """

    session = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)()
    session.info[TENANT] = default_user.id
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def session(db: Session) -> Session:
    """Alias for ``db`` — same object, historical name."""

    return db


@contextmanager
def override_dependencies(
    overrides: dict[Callable[..., object], Callable[..., object]],
) -> Iterator[None]:
    """Install dependency overrides and restore what was there before.

    Keyed by the dependency callable itself, which is why this takes a dict
    rather than kwargs.

    ``app.dependency_overrides.clear()`` — what the old per-module fixtures did
    — wipes *every* override, not just the ones a fixture installed. That is a
    footgun as soon as a second override exists, so save and restore instead.
    """

    saved = dict(app.dependency_overrides)
    app.dependency_overrides.update(overrides)
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


@pytest.fixture
def client(engine: Engine, db: Session, default_user: User) -> Iterator[TestClient]:
    """A TestClient authenticated as ``default_user`` via dependency override.

    Shares the test's Session so test-side writes are visible to requests.
    Convenience for tests that are not *about* authentication; anything
    asserting isolation must use ``client_as`` and real tokens instead.
    """

    def _override_get_db() -> Iterator[Session]:
        yield db

    def _override_user() -> User:
        return default_user

    with override_dependencies(
        {get_db: _override_get_db, current_user_optional: _override_user}
    ):
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def anonymous_client(engine: Engine) -> Iterator[TestClient]:
    """No token and NO dependency overrides — the real guard runs."""

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def client_as(engine: Engine) -> Iterator[Callable[[User], TestClient]]:
    """Build a TestClient holding a REAL access token for ``user``.

    Logs in over HTTP against /api/auth/login and sets the Authorization header
    from the response, so requests traverse the true path: HTTPBearer ->
    resolve_access_token -> get_current_user -> get_db's tenant binding.

    NOTHING is overridden. The engine fixture has already rebound SessionLocal
    to the in-memory database, so the real dependencies run unmodified and the
    tenant comes from the token rather than from a fixture.
    """

    clients: list[TestClient] = []

    def _build(user: User, password: str = DEFAULT_PASSWORD) -> TestClient:
        c = TestClient(app)
        c.__enter__()
        clients.append(c)
        resp = c.post(
            "/api/auth/login", json={"email": user.email, "password": password}
        )
        assert resp.status_code == 200, f"login failed: {resp.text}"
        body = resp.json()
        token = body["access_token"]
        assert token.startswith("env_at_")
        c.headers["Authorization"] = f"Bearer {token}"
        # Stashed so isolation tests can attack a REAL refresh token rather
        # than a made-up string.
        c._envelope_refresh_token = body["refresh_token"]  # type: ignore[attr-defined]
        return c

    try:
        yield _build
    finally:
        for c in clients:
            c.__exit__(None, None, None)


@pytest.fixture(autouse=True)
def never_reach_simplefin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make any outbound HTTP request from the sync code a hard failure.

    CLAUDE.md and .claude/rules/testing.md forbid claiming a SimpleFIN setup
    token from a test: they are one-time, and burning one costs a manual
    regeneration.

    The guard is on the NETWORK boundary, not on ``claim_setup_token`` itself.
    That function decodes the token first and raises ``SetupTokenError`` for
    anything malformed before it opens a socket, so the malformed-token test is
    legitimately safe and must keep working. What must never happen is the
    request actually going out — which is also what would burn a real token.
    """

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "A test tried to make a real HTTP request to SimpleFIN. Setup "
            "tokens are one-time; use the recorded fixture instead."
        )

    monkeypatch.setattr("urllib.request.urlopen", _boom)
    monkeypatch.setattr("app.sync.simplefin._http_get_json", _boom)


@pytest.fixture(autouse=True)
def reset_process_globals() -> Iterator[None]:
    """Clear process-global caches around every test.

    ``_STAGED`` (import staging) and ``_DISCOVERED`` (sync discovery) outlive a
    test's database. Leaking them between tests is precisely the bug class this
    suite exists to catch, so it must not be able to happen by accident.
    """

    from app.routers import imports as imports_router
    from app.sync import service as sync_service

    imports_router._STAGED.clear()
    sync_service._DISCOVERED.clear()
    yield
    imports_router._STAGED.clear()
    sync_service._DISCOVERED.clear()

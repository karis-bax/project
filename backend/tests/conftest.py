"""Shared test fixtures.

Previously every DB-using test module hand-rolled the same in-memory engine,
under two different names (``session`` in test_api/test_soft_delete, ``db`` in
test_budget/test_sync). They are consolidated here; ``session`` is an alias
fixture depending on ``db``, so both names resolve to the *same* Session object
and no existing test body needed rewriting.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app


@pytest.fixture
def engine() -> Iterator[Engine]:
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
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """The canonical session fixture.

    ``expire_on_commit=False`` so tests can read ``.id`` off ORM objects after
    an HTTP call has committed.
    """

    session = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)()
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
def client(db: Session) -> Iterator[TestClient]:
    """A TestClient whose requests share the test's Session."""

    def _override_get_db() -> Iterator[Session]:
        yield db

    with override_dependencies({get_db: _override_get_db}):
        with TestClient(app) as test_client:
            yield test_client


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

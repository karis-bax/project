"""Database engine, session factory, declarative base, and FastAPI dependency.

Money is always stored as signed integer cents (see ``models.py``); nothing in
this layer performs float or Decimal conversions.
"""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import (
    DeclarativeBase,
    ORMExecuteState,
    Session,
    sessionmaker,
    with_loader_criteria,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./envelope.db")

# Execution option to opt OUT of the soft-delete filter (restore/revive/purge).
INCLUDE_DELETED = "include_deleted"

# ``check_same_thread`` only matters for SQLite; it lets the connection be used
# across threads (FastAPI's threadpool for sync endpoints).
_connect_args = (
    {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=Session,
)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(state: ORMExecuteState) -> None:
    """Exclude soft-deleted transactions from EVERY ORM read, in one place.

    Using ``with_loader_criteria`` at the Session level makes an unfiltered read
    impossible by construction — no scattered ``.where(deleted_at.is_(None))``
    to forget. Callers that must see soft-deleted rows (restore, revive, purge)
    pass ``execution_options(include_deleted=True)``. (This is the same
    mechanism a future multi-tenant auth layer would use for row scoping.)
    """

    if not state.is_select or state.execution_options.get(INCLUDE_DELETED):
        return
    # Imported lazily to avoid a circular import (models imports Base).
    from .models import Transaction

    state.statement = state.statement.options(
        with_loader_criteria(
            Transaction,
            lambda cls: cls.deleted_at.is_(None),
            include_aliases=True,
        )
    )


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped SQLAlchemy session."""

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

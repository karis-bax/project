"""Database engine, session factory, declarative base, and row-level filters.

Money is always stored as signed integer cents (see ``models.py``); nothing in
this layer performs float or Decimal conversions.

Two independent row filters are enforced here, at the Session level, so that no
caller can forget them:

1. **Soft delete** — ``Transaction.deleted_at IS NULL``. Opt out per statement
   with ``execution_options(include_deleted=True)``.
2. **Tenant scope** — ``<Owned>.user_id == this session's user``. There is
   deliberately **no execution option** for this. The only way to run unscoped
   is ``unscoped_session(reason=...)``, a named context manager used at a
   handful of audited sites.

Keeping the tenant opt-out off the statement is what makes the two filters
compose: a per-statement ``all_users=True`` would sit one keystroke from
``include_deleted=True`` in every router, and the claim that the two are
independent would rest on nobody ever typing it.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import contextmanager

from sqlalchemy import Table, create_engine, event, inspect
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapper,
    ORMExecuteState,
    Session,
    sessionmaker,
    with_loader_criteria,
)
from sqlalchemy.sql import visitors

from .settings import settings

DATABASE_URL = settings.database_url

# Execution option to opt OUT of the soft-delete filter (restore/revive/purge).
INCLUDE_DELETED = "include_deleted"

# ``Session.info`` key holding this session's tenant: an int user id, or the
# ALL_USERS sentinel. Absent means unscoped, which is an error.
TENANT = "tenant_scope"

# Execution option acknowledging that a raw/Core statement cannot be
# tenant-filtered automatically and has been checked by hand.
RAW_SQL_REVIEWED = "raw_sql_reviewed"


class _AllUsers:
    """Sentinel marking a Session that deliberately spans every user."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "ALL_USERS"


ALL_USERS = _AllUsers()


class TenantScopeError(RuntimeError):
    """A tenant-owned entity was touched by a session with no tenant scope."""


class CrossTenantWrite(RuntimeError):
    """A write tried to set or move ``user_id`` away from the session's tenant."""


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


_owned_by_table: dict[str, Mapper] | None = None


def owned_mappers() -> dict[str, Mapper]:
    """Map table name -> mapper for every model carrying ``OwnedMixin``.

    Discovered by subclass rather than listed, so a new owned model is picked
    up automatically. Computed once, lazily (models imports Base).
    """

    global _owned_by_table
    if _owned_by_table is None:
        from .models import OwnedMixin

        _owned_by_table = {
            mapper.local_table.name: mapper
            for mapper in Base.registry.mappers
            if issubclass(mapper.class_, OwnedMixin)
        }
    return _owned_by_table


def _referenced_tables(statement: object) -> set[str]:
    """Every table name a statement references, at any depth.

    Walking the statement rather than reading ``ORMExecuteState.all_mappers``
    is deliberate: ``all_mappers`` is EMPTY for column-only aggregates such as
    ``select(func.count()).select_from(Transaction)``, so it cannot distinguish
    "touches no owned table" from "touches one via an aggregate". Getting that
    backwards either leaks rows or raises on the auth tables' own queries.
    """

    return {
        element.name
        for element in visitors.iterate(statement)
        if isinstance(element, Table)
    }


def tenant_id(session: Session) -> int:
    """This session's user id. Raises unless the session is user-scoped.

    The single source of truth for code that must supply ``user_id`` by hand —
    notably the Allocation upsert, which is a Core INSERT the listener cannot
    reach.
    """

    scope = session.info.get(TENANT)
    if not isinstance(scope, int):
        raise TenantScopeError(
            f"This operation requires a user-scoped Session; scope is {scope!r}."
        )
    return scope


@event.listens_for(Session, "do_orm_execute")
def _apply_row_filters(state: ORMExecuteState) -> None:
    """Apply the soft-delete and tenant filters. Two guards, no shared return.

    Nothing may ``return`` between the two blocks: they are independent, and
    the whole point is that one filter's opt-out cannot disable the other.
    """

    if state.is_insert:
        # Nothing to constrain on an INSERT, and with_loader_criteria has no
        # meaning there. Inserts into filtered tables carry their own
        # correctness (Allocation upsert) and are backstopped by user_id being
        # NOT NULL.
        return

    tables = _referenced_tables(state.statement)

    # --- 1. soft delete ----------------------------------------------------
    if not state.execution_options.get(INCLUDE_DELETED) and "transactions" in tables:
        from .models import Transaction

        state.statement = state.statement.options(
            with_loader_criteria(
                Transaction,
                lambda cls: cls.deleted_at.is_(None),
                include_aliases=True,
            )
        )

    # --- 2. tenant scope ---------------------------------------------------
    # NOTE: no `return` above this line. Ever.
    scope = state.session.info.get(TENANT)
    if scope is ALL_USERS:
        return

    owned = owned_mappers()
    touched = tables & owned.keys()
    if not touched:
        # Includes the auth tables (users, refresh_tokens, login_attempts),
        # which is what lets an unscoped session resolve credentials at login.
        return

    if not isinstance(scope, int):
        raise TenantScopeError(
            "A tenant-owned table "
            f"({', '.join(sorted(touched))}) was queried by a Session with no "
            "tenant scope. Request sessions come from get_db, which requires "
            "an authenticated user; everything else must use "
            "unscoped_session(reason=...)."
        )

    if not tables and not state.execution_options.get(RAW_SQL_REVIEWED):
        raise TenantScopeError(  # pragma: no cover - no raw SQL in app/ today
            "Non-ORM SQL cannot be tenant-scoped automatically. Rewrite it as "
            "an ORM statement, or add execution_options(raw_sql_reviewed=True) "
            "after proving it is already scoped."
        )

    state.statement = state.statement.options(
        *[
            with_loader_criteria(
                owned[table].class_,
                owned[table].class_.user_id == scope,
                include_aliases=True,
            )
            for table in sorted(touched)
        ]
    )


@event.listens_for(Session, "before_flush")
def _stamp_and_pin_tenant(session: Session, _flush_context: object, _instances: object) -> None:
    """Stamp ``user_id`` on new owned rows and refuse cross-tenant writes.

    This is where "every write sets user_id from the authenticated session,
    never from the request body" is actually enforced. It has to be here rather
    than in the routers because owned objects are constructed in places with no
    request context at all — the sync engine, the CSV importer, the seeder.

    ``do_orm_execute`` does not fire during flush, so the listener above cannot
    do this.
    """

    from .models import OwnedMixin

    scope = session.info.get(TENANT)

    for obj in session.new:
        if not isinstance(obj, OwnedMixin):
            continue
        if scope is ALL_USERS:
            if obj.user_id is None:
                raise TenantScopeError(
                    f"{type(obj).__name__} inserted by an unscoped session must "
                    "set user_id explicitly."
                )
            continue
        if not isinstance(scope, int):
            raise TenantScopeError(
                f"Cannot insert {type(obj).__name__}: session has no tenant scope."
            )
        if obj.user_id is not None and obj.user_id != scope:
            raise CrossTenantWrite(
                f"{type(obj).__name__}.user_id={obj.user_id} does not match the "
                f"session tenant {scope}. user_id comes from the session, never "
                "from a request body."
            )
        obj.user_id = scope

    # A row never changes owner.
    for obj in session.dirty:
        if not isinstance(obj, OwnedMixin):
            continue
        history = inspect(obj).attrs.user_id.history
        if history.has_changes() and history.deleted:
            raise CrossTenantWrite(
                f"{type(obj).__name__}.user_id is immutable "
                f"({history.deleted[0]} -> {history.added[0] if history.added else None})."
            )


@contextmanager
def unscoped_session(*, reason: str) -> Iterator[Session]:
    """The ONLY way to obtain a Session that spans every user.

    This is the escape hatch from tenant scoping, and it is deliberately
    awkward: a named context manager taking a mandatory ``reason``, rather than
    a keyword argument any call site could pass. An opt-out that is casual to
    write is the bypass, and the listener would decay back into discipline.

    Every call site is enumerated by
    ``tests/test_tenant_isolation.py::test_unscoped_session_call_sites``, which
    fails when one is added or removed. Adding a legitimate one means updating
    that list in the same commit, where a reviewer sees it.

    Use for genuinely cross-user maintenance only: the purge job, the seeder,
    analysis scripts, and resolving credentials before a user is known.
    """

    if not reason or not reason.strip():
        raise ValueError("unscoped_session requires a non-empty reason.")
    db = SessionLocal()
    db.info[TENANT] = ALL_USERS
    try:
        yield db
    finally:
        db.close()


@contextmanager
def user_session(user_id: int) -> Iterator[Session]:
    """A Session scoped to one user, outside a request (scripts, migrations)."""

    db = SessionLocal()
    db.info[TENANT] = user_id
    try:
        yield db
    finally:
        db.close()


# NOTE: get_db lives in deps.py, not here. It depends on the authenticated user
# (so that a request Session cannot exist without a tenant), and auth imports
# models which imports this module — defining it here would be circular.

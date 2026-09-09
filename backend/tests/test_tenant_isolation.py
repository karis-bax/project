"""The tenant-scoping mechanism itself: composition, fail-closed, and the bans.

These test the machinery in app/db.py rather than any route. The route-level
proof lives in test_cross_user_isolation.py.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import (
    ALL_USERS,
    TENANT,
    Base,
    CrossTenantWrite,
    TenantScopeError,
    owned_mappers,
)
from app.models import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    Transaction,
    TxnSource,
    User,
)

BACKEND = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# The escape hatch: every call site, enumerated.
# ---------------------------------------------------------------------------

# unscoped_session() is the ONLY way past tenant scoping. Each entry is
# (path relative to backend/, function it appears in). Adding a call site means
# editing this list in the same commit, where a reviewer sees it.
#
# Keep this SMALL. Every entry is a place where one user's session can read
# another user's rows.
EXPECTED_UNSCOPED_CALL_SITES: frozenset[tuple[str, str]] = frozenset(
    {
        ("app/seed.py", "main"),
        # Sets a password before any user is authenticated, so there is no
        # scope to run under; it must find the user first.
        ("scripts/set_password.py", "main"),
        ("scripts/purge_soft_deleted.py", "main"),
        ("scripts/analyze_pending.py", "main"),
    }
)


def _enclosing_function(tree: ast.Module, node: ast.AST) -> str:
    """Name of the function containing ``node``, or '<module>'."""

    best = "<module>"
    for candidate in ast.walk(tree):
        if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                candidate.lineno <= node.lineno
                and getattr(node, "end_lineno", node.lineno)
                <= (candidate.end_lineno or node.lineno)
            ):
                best = candidate.name
    return best


def _find_calls(name: str, roots: tuple[str, ...]) -> set[tuple[str, str]]:
    sites: set[tuple[str, str]] = set()
    for root in roots:
        for path in sorted((BACKEND / root).rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                func_node = node.func if isinstance(node, ast.Call) else None
                called = getattr(func_node, "id", None) or getattr(
                    func_node, "attr", None
                )
                if called == name:
                    rel = str(path.relative_to(BACKEND))
                    sites.add((rel, _enclosing_function(tree, node)))
    return sites


def test_unscoped_session_call_sites() -> None:
    """The tenant escape hatch is used at exactly the audited sites.

    Fails in BOTH directions. A new call site is a deliberate widening of the
    isolation boundary and must be reviewed; a stale entry means the list has
    drifted from the code and is no longer telling the truth.
    """

    found = {
        site
        for site in _find_calls("unscoped_session", ("app", "scripts"))
        if site != ("app/db.py", "unscoped_session")
    }

    added = found - EXPECTED_UNSCOPED_CALL_SITES
    assert not added, (
        f"New unscoped_session() call site(s): {sorted(added)}. Each one can "
        "read every user's rows. If it is genuinely cross-user maintenance, add "
        "it to EXPECTED_UNSCOPED_CALL_SITES in the same commit."
    )
    removed = EXPECTED_UNSCOPED_CALL_SITES - found
    assert not removed, (
        f"Expected unscoped_session() call site(s) are gone: {sorted(removed)}. "
        "Remove them from EXPECTED_UNSCOPED_CALL_SITES."
    )


def test_unscoped_session_requires_a_reason() -> None:
    from app.db import unscoped_session

    with pytest.raises(TypeError):
        unscoped_session()  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        with unscoped_session(reason="   "):
            pass


def test_no_session_get_on_a_tenant_scoped_model() -> None:
    """Session.get() is banned for owned models.

    It returns identity-map hits without emitting SQL, so do_orm_execute never
    fires and neither filter applies — it can hand back another user's row.
    Use deps.get_live_or_404, which always emits a SELECT.

    AST rather than grep: grep for `db.get(` misses `session.get(` and
    `self._db.get(`, while false-positiving on dict.get / os.environ.get /
    headers.get, which appear throughout.
    """

    owned_names = {mapper.class_.__name__ for mapper in owned_mappers().values()}
    violations: list[str] = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in owned_names
            ):
                violations.append(
                    f"{path.relative_to(BACKEND)}:{node.lineno} "
                    f"get({node.args[0].id}, ...)"
                )
    assert not violations, (
        "Session.get() on a tenant-scoped model at: " + ", ".join(violations)
        + ". Use deps.get_live_or_404(db, Model, id) — it always emits a "
        "SELECT, so the session filters always apply."
    )


def test_no_bulk_dml_on_a_tenant_scoped_model() -> None:
    """Bulk update()/delete() must not be written against owned models in app/.

    The listener does constrain ORM-enabled UPDATE/DELETE, so these are not
    unsafe today — but they bypass the before_flush stamper, produce row counts
    that silently differ from rows touched, and are one refactor away from
    being raw Core statements that nothing filters. Load and modify through the
    ORM instead.
    """

    owned_names = {mapper.class_.__name__ for mapper in owned_mappers().values()}
    violations: list[str] = []
    for path in sorted((BACKEND / "app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"update", "delete", "sqlite_insert", "insert"}
                and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in owned_names
            ):
                violations.append(
                    f"{path.relative_to(BACKEND)}:{node.lineno} "
                    f"{node.func.id}({node.args[0].id})"
                )
    # The Allocation upsert is a reviewed exception: it is a Core INSERT that
    # supplies user_id from tenant_id(db), asserted by
    # test_allocation_upsert_stamps_the_session_user below.
    allowed = {"app/routers/budget.py"}
    unexpected = [v for v in violations if v.split(":")[0] not in allowed]
    assert not unexpected, (
        "Bulk DML on a tenant-scoped model at: " + ", ".join(unexpected)
    )


def test_every_model_is_tenant_owned() -> None:
    """A new model must declare whether it is owned."""

    not_owned = {"User", "TokenFamily", "AccessToken", "RefreshToken", "LoginAttempt"}
    owned_names = {mapper.class_.__name__ for mapper in owned_mappers().values()}
    all_names = {mapper.class_.__name__ for mapper in Base.registry.mappers}
    unclassified = all_names - owned_names - not_owned
    assert not unclassified, (
        f"Model(s) {sorted(unclassified)} are neither OwnedMixin nor listed as "
        "deliberately unowned. Add OwnedMixin, or add to not_owned with a reason."
    )


# ---------------------------------------------------------------------------
# Composition: the two filters are independent.
# ---------------------------------------------------------------------------


@pytest.fixture
def two_users(engine: Engine) -> tuple[User, User]:
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    with factory() as s:
        a = User(email="a@example.com", password_hash="x")
        b = User(email="b@example.com", password_hash="x")
        s.add_all([a, b])
        s.commit()
        s.refresh(a)
        s.refresh(b)
        return a, b


def _scoped(engine: Engine, scope: object) -> Session:
    s = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)()
    s.info[TENANT] = scope
    return s


def _seed_for(session: Session, marker: str) -> tuple[int, int]:
    """One live and one soft-deleted transaction for the session's user."""

    account = Account(
        name=f"{marker}-account",
        kind=AccountKind.checking,
        opening_balance_cents=0,
        archived=False,
    )
    group = CategoryGroup(name=f"{marker}-group", sort_order=0)
    session.add_all([account, group])
    session.flush()
    category = Category(
        group_id=group.id, name=f"{marker}-cat", sort_order=0, archived=False
    )
    session.add(category)
    session.flush()
    live = Transaction(
        account_id=account.id,
        category_id=category.id,
        date=date(2026, 4, 1),
        payee=f"{marker}-live",
        amount_cents=-1000,
        source=TxnSource.manual,
    )
    gone = Transaction(
        account_id=account.id,
        category_id=category.id,
        date=date(2026, 4, 2),
        payee=f"{marker}-deleted",
        amount_cents=-2000,
        source=TxnSource.manual,
        deleted_at=date(2026, 4, 3),
    )
    session.add_all([live, gone])
    session.commit()
    return live.id, gone.id


def test_soft_delete_and_tenant_compose(engine: Engine, two_users) -> None:
    """Both filters apply, and neither opt-out disables the other."""

    user_a, user_b = two_users
    sa, sb = _scoped(engine, user_a.id), _scoped(engine, user_b.id)
    a_live, a_deleted = _seed_for(sa, "A")
    b_live, b_deleted = _seed_for(sb, "B")

    # Both filters applied.
    assert {t.id for t in sa.scalars(select(Transaction))} == {a_live}

    # include_deleted lifts soft delete and NOTHING else: B's rows stay hidden.
    seen = {
        t.id
        for t in sa.scalars(
            select(Transaction).execution_options(include_deleted=True)
        )
    }
    assert seen == {a_live, a_deleted}
    assert b_live not in seen and b_deleted not in seen

    # The single most important assertion in this file: the soft-delete opt-out
    # is not a tenant opt-out.
    assert (
        sa.scalar(
            select(Transaction)
            .where(Transaction.id == b_deleted)
            .execution_options(include_deleted=True)
        )
        is None
    )

    # Aggregates (all_mappers is empty for these) are filtered too.
    assert sa.scalar(select(func.count()).select_from(Transaction)) == 1
    assert sa.scalar(select(func.sum(Transaction.amount_cents))) == -1000


def test_unscoped_session_fails_closed(engine: Engine, two_users) -> None:
    """No scope means raise, not 'return nothing'.

    Returning nothing would be indistinguishable from an empty database and
    would ship as "the new user's dashboard is empty".
    """

    user_a, _ = two_users
    _seed_for(_scoped(engine, user_a.id), "A")

    bare = sessionmaker(bind=engine, class_=Session)()  # no info[TENANT]
    with pytest.raises(TenantScopeError):
        bare.scalars(select(Transaction)).all()

    # And the soft-delete opt-out does not become a tenant opt-out by omission.
    with pytest.raises(TenantScopeError):
        bare.scalars(
            select(Transaction).execution_options(include_deleted=True)
        ).all()

    # Non-owned tables are still readable — this is what lets login work.
    assert bare.scalars(select(User)).all()


def test_all_users_does_not_disable_soft_delete(engine: Engine, two_users) -> None:
    """The converse: the tenant escape hatch does not lift soft delete."""

    user_a, user_b = two_users
    a_live, a_deleted = _seed_for(_scoped(engine, user_a.id), "A")
    b_live, _b_deleted = _seed_for(_scoped(engine, user_b.id), "B")

    everyone = _scoped(engine, ALL_USERS)
    assert {t.id for t in everyone.scalars(select(Transaction))} == {a_live, b_live}
    assert a_deleted not in {t.id for t in everyone.scalars(select(Transaction))}


def test_writes_are_stamped_from_the_session(engine: Engine, two_users) -> None:
    user_a, _ = two_users
    sa = _scoped(engine, user_a.id)
    group = CategoryGroup(name="stamped", sort_order=0)
    sa.add(group)
    sa.commit()
    assert group.user_id == user_a.id, "user_id came from the session"


def test_write_for_another_user_is_refused(engine: Engine, two_users) -> None:
    user_a, user_b = two_users
    sa = _scoped(engine, user_a.id)
    sa.add(CategoryGroup(name="smuggled", sort_order=0, user_id=user_b.id))
    with pytest.raises(CrossTenantWrite):
        sa.flush()


def test_user_id_is_immutable(engine: Engine, two_users) -> None:
    user_a, user_b = two_users
    sa = _scoped(engine, user_a.id)
    group = CategoryGroup(name="mine", sort_order=0)
    sa.add(group)
    sa.commit()

    group.user_id = user_b.id
    with pytest.raises(CrossTenantWrite):
        sa.flush()

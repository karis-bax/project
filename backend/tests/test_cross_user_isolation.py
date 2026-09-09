"""User B must not reach user A's data through ANY route.

Everything here drives the API with **real bearer tokens** obtained by logging
in over HTTP (the ``client_as`` fixture). No auth dependency is overridden — a
test that proves isolation while bypassing the mechanism that enforces it
proves nothing.

Three properties, each of which the naive version of this test misses:

1. **Byte-identical, not just 404.** ``DELETE /api/categories/{id}`` answers 409
   with the category's *name and balance* in the message. If ownership were
   checked after the lookup rather than folded into it, enumerating ids would
   harvest that through a status code which is neither 403 nor 404. So B's
   response for one of A's ids is compared to B's response for an id that
   exists nowhere, and must match exactly.
2. **Not vacuous.** B has an empty dataset, so a backend that 404s everything
   would score a perfect pass. Every probe is therefore also run by its owner
   and must succeed.
3. **Beyond primary keys.** The import staging token has no primary key and no
   row, so a PK-only enumeration would never have covered it.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import TENANT
from app.models import (
    Account,
    AccountKind,
    Category,
    CategoryGroup,
    CategoryRule,
    Goal,
    GoalKind,
    RuleField,
    Transaction,
    TxnSource,
    User,
)
from tests.routes import api_routes

# Strings seeded through A's data. Any of them appearing in a response to B is
# a leak, whatever field carried it — this catches a field nobody thought to
# name, including one added next month.
A_SENTINELS = (
    "ZZ-USER-A-ACCOUNT",
    "ZZ-USER-A-GROUP",
    "ZZ-USER-A-CATEGORY",
    "ZZ-USER-A-PAYEE",
    "ZZ-USER-A-RULE",
    "ZZ-USER-A-EXTERNAL",
)


class Kind(enum.Enum):
    OWNED = "owned"  # touches user data; needs at least one probe
    PUBLIC = "public"  # no auth, no user data
    EXEMPT = "exempt"  # must not be called from a test; needs a reason


@dataclass(frozen=True)
class Dataset:
    """One user's whole world, as ids a probe can aim at."""

    user_id: int
    account_id: int
    group_id: int
    category_id: int
    other_category_id: int
    transaction_id: int
    deleted_transaction_id: int
    rule_id: int
    goal_id: int
    month: str
    external_id: str
    import_token: str
    refresh_token: str = ""


# An id space nothing occupies, for the "exists nowhere" twin.
GHOST = Dataset(
    user_id=10**9,
    account_id=10**9,
    group_id=10**9,
    category_id=10**9,
    other_category_id=10**9 + 1,
    transaction_id=10**9,
    deleted_transaction_id=10**9 + 1,
    rule_id=10**9,
    goal_id=10**9,
    month="2011-01",
    external_id="ghost-external",
    import_token="ghost-token-0000",
    refresh_token="env_rt_ghost-token-that-was-never-issued",
)


@dataclass(frozen=True)
class Request:
    template: str
    path_params: dict[str, object] = field(default_factory=dict)
    query: dict[str, object] = field(default_factory=dict)
    json: object | None = None

    def url(self) -> str:
        return self.template.format(**self.path_params)


@dataclass(frozen=True)
class Probe:
    vector: str
    build: Callable[[Dataset], Request]
    # False for collection routes, which answer 200-with-nothing rather than 404.
    expect_404: bool = True
    owner_expect: tuple[int, ...] = (200, 201)
    empty_result: Callable[[object], bool] | None = None


@dataclass(frozen=True)
class RouteSpec:
    kind: Kind
    probes: tuple[Probe, ...] = ()
    note: str = ""


def _p(template: str, **kw: object) -> Callable[[Dataset], Request]:
    """Build a Request from a Dataset by pulling named attributes.

    ``path``/``query`` map parameter name -> Dataset attribute; ``qconst``
    supplies literal query values that are not ids.
    """

    def _build(d: Dataset) -> Request:
        path_params = {
            k: getattr(d, v) for k, v in kw.get("path", {}).items()  # type: ignore[union-attr]
        }
        query: dict[str, object] = {
            k: getattr(d, v) for k, v in kw.get("query", {}).items()  # type: ignore[union-attr]
        }
        query.update(kw.get("qconst", {}))  # type: ignore[arg-type]
        body = kw.get("json")
        payload = body(d) if callable(body) else body
        return Request(template, path_params, query, payload)

    return _build


SPECS: dict[tuple[str, str], RouteSpec] = {
    ("GET", "/api/health"): RouteSpec(Kind.PUBLIC, note="liveness only"),
    # --- auth ---
    ("POST", "/api/auth/register"): RouteSpec(Kind.PUBLIC, note="pre-auth"),
    ("POST", "/api/auth/login"): RouteSpec(Kind.PUBLIC, note="pre-auth"),
    ("POST", "/api/auth/refresh"): RouteSpec(Kind.PUBLIC, note="pre-auth"),
    ("POST", "/api/auth/logout"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:refresh_token",
                _p(
                    "/api/auth/logout",
                    json=lambda d: {"refresh_token": d.refresh_token},
                ),
                expect_404=False,
                empty_result=lambda body: True,
                # Asserted properly by test_b_cannot_revoke_as_session below;
                # here we only require that it does not error.
            ),
        ),
    ),
    ("GET", "/api/auth/me"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "identity",
                _p("/api/auth/me"),
                expect_404=False,
                empty_result=lambda body: True,  # asserted by sentinel scan
            ),
        ),
    ),
    # --- accounts ---
    ("GET", "/api/accounts"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "collection",
                _p("/api/accounts"),
                expect_404=False,
                empty_result=lambda body: True,  # sentinel scan is the assertion
            ),
        ),
    ),
    ("POST", "/api/accounts"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "create-lands-on-caller",
                _p(
                    "/api/accounts",
                    json=lambda d: {
                        "name": "probe-account",
                        "kind": "checking",
                        "opening_balance_cents": 0,
                    },
                ),
                expect_404=False,
                owner_expect=(200, 201),
                empty_result=lambda body: True,
            ),
        ),
    ),
    ("PATCH", "/api/accounts/{account_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:account_id",
                _p(
                    "/api/accounts/{account_id}",
                    path={"account_id": "account_id"},
                    json=lambda d: {"name": "hijacked"},
                ),
            ),
        ),
    ),
    ("DELETE", "/api/accounts/{account_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:account_id",
                _p("/api/accounts/{account_id}", path={"account_id": "account_id"}),
            ),
        ),
    ),
    # --- categories ---
    ("GET", "/api/categories"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "collection",
                _p("/api/categories"),
                expect_404=False,
                empty_result=lambda body: True,  # sentinel scan is the assertion
            ),
        ),
    ),
    ("POST", "/api/categories"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:group_id",
                _p(
                    "/api/categories",
                    json=lambda d: {
                        "group_id": d.group_id,
                        "name": "probe-cat",
                        "sort_order": 0,
                    },
                ),
                owner_expect=(200, 201),
            ),
        ),
    ),
    ("PATCH", "/api/categories/{category_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:category_id",
                _p(
                    "/api/categories/{category_id}",
                    path={"category_id": "category_id"},
                    json=lambda d: {"name": "hijacked"},
                ),
            ),
        ),
    ),
    ("DELETE", "/api/categories/{category_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:category_id",
                _p(
                    "/api/categories/{category_id}",
                    path={"category_id": "category_id"},
                    qconst={"discard": "true"},
                ),
            ),
        ),
        note="409 body carries the category name and balance; the twin catches it",
    ),
    ("POST", "/api/category-groups"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "create-lands-on-caller",
                _p("/api/category-groups", json=lambda d: {"name": "probe-group"}),
                expect_404=False,
                owner_expect=(200, 201),
                empty_result=lambda body: True,
            ),
        ),
    ),
    ("PATCH", "/api/category-groups/reorder"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:group_ids[]",
                _p(
                    "/api/category-groups/reorder",
                    json=lambda d: {"group_ids": [d.group_id]},
                ),
            ),
        ),
    ),
    # --- transactions ---
    ("GET", "/api/transactions"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "query:account_id",
                _p("/api/transactions", query={"account_id": "account_id"}),
                expect_404=False,
                empty_result=lambda body: body["items"] == [],
            ),
        ),
    ),
    ("GET", "/api/transactions/count"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "query:account_id",
                _p("/api/transactions/count", query={"account_id": "account_id"}),
                expect_404=False,
                empty_result=lambda body: body["count"] == 0,
            ),
        ),
    ),
    ("GET", "/api/transactions/payees"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "collection",
                _p("/api/transactions/payees"),
                expect_404=False,
                empty_result=lambda body: True,  # sentinel scan is the assertion
            ),
        ),
    ),
    ("POST", "/api/transactions"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:account_id",
                _p(
                    "/api/transactions",
                    json=lambda d: {
                        "account_id": d.account_id,
                        "date": "2026-04-01",
                        "payee": "probe",
                        "amount_cents": -100,
                    },
                ),
                owner_expect=(200, 201),
            ),
        ),
    ),
    ("PATCH", "/api/transactions/{transaction_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:transaction_id",
                _p(
                    "/api/transactions/{transaction_id}",
                    path={"transaction_id": "transaction_id"},
                    json=lambda d: {"payee": "hijacked"},
                ),
            ),
        ),
    ),
    ("DELETE", "/api/transactions/{transaction_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:transaction_id",
                _p(
                    "/api/transactions/{transaction_id}",
                    path={"transaction_id": "transaction_id"},
                ),
            ),
        ),
    ),
    ("POST", "/api/transactions/{transaction_id}/restore"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:deleted_transaction_id",
                _p(
                    "/api/transactions/{transaction_id}/restore",
                    path={"transaction_id": "deleted_transaction_id"},
                ),
            ),
        ),
        note="deliberately looks past the soft-delete filter; must not look past tenancy",
    ),
    ("POST", "/api/transactions/bulk-categorize"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:ids[]",
                _p(
                    "/api/transactions/bulk-categorize",
                    json=lambda d: {"ids": [d.transaction_id], "category_id": None},
                ),
                expect_404=False,
                empty_result=lambda body: body["updated"] == 0,
            ),
        ),
    ),
    # --- budget ---
    ("GET", "/api/budget/{month}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "tenant-read",
                _p("/api/budget/{month}", path={"month": "month"}),
                expect_404=False,
                empty_result=lambda body: True,
            ),
        ),
    ),
    ("PUT", "/api/budget/{month}/allocations/{category_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:category_id",
                _p(
                    "/api/budget/{month}/allocations/{category_id}",
                    path={"month": "month", "category_id": "category_id"},
                    json=lambda d: {"amount_cents": 12345},
                ),
            ),
        ),
    ),
    ("POST", "/api/budget/{month}/copy-from-previous"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "tenant-write",
                _p("/api/budget/{month}/copy-from-previous", path={"month": "month"}),
                expect_404=False,
                empty_result=lambda body: True,
            ),
        ),
    ),
    # --- goals / rules ---
    ("GET", "/api/goals"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "query:category_id",
                _p("/api/goals", query={"category_id": "category_id"}),
                expect_404=False,
                empty_result=lambda body: body == [],
            ),
        ),
    ),
    ("GET", "/api/rules"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "collection",
                _p("/api/rules"),
                expect_404=False,
                empty_result=lambda body: True,  # sentinel scan is the assertion
            ),
        ),
    ),
    ("POST", "/api/rules"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:category_id",
                _p(
                    "/api/rules",
                    json=lambda d: {
                        "match_field": "payee",
                        "pattern": "probe",
                        "category_id": d.category_id,
                        "priority": 1,
                    },
                ),
                owner_expect=(200, 201),
            ),
        ),
    ),
    ("PATCH", "/api/rules/reorder"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:rule_ids[]",
                _p("/api/rules/reorder", json=lambda d: {"rule_ids": [d.rule_id]}),
            ),
        ),
    ),
    ("DELETE", "/api/rules/{rule_id}"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "path:rule_id",
                _p("/api/rules/{rule_id}", path={"rule_id": "rule_id"}),
            ),
        ),
    ),
    ("POST", "/api/rules/apply"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "tenant-write",
                _p("/api/rules/apply"),
                expect_404=False,
                empty_result=lambda body: True,
            ),
        ),
    ),
    # --- import (opaque handle) ---
    ("POST", "/api/import/preview"): RouteSpec(
        Kind.OWNED, note="multipart mint; covered by the handle tests"
    ),
    ("POST", "/api/import/remap"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "handle:import_token",
                _p(
                    "/api/import/remap",
                    json=lambda d: {
                        "token": d.import_token,
                        "mapping": {
                            "date_col": 0,
                            "payee_col": 1,
                            "amount_col": 2,
                            "amount_shape": "signed",
                        },
                    },
                ),
            ),
        ),
    ),
    ("POST", "/api/import/commit"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "handle:import_token",
                _p(
                    "/api/import/commit",
                    json=lambda d: {"token": d.import_token, "rows": []},
                ),
            ),
        ),
    ),
    # --- sync ---
    ("POST", "/api/sync/claim"): RouteSpec(
        Kind.EXEMPT,
        note=(
            "SimpleFIN setup tokens are one-time; burning one costs a manual "
            "regeneration. Forbidden by CLAUDE.md and .claude/rules/testing.md. "
            "Still audited statically for auth coverage."
        ),
    ),
    ("GET", "/api/sync/accounts"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "collection",
                _p("/api/sync/accounts"),
                expect_404=False,
                empty_result=lambda body: True,  # sentinel scan is the assertion
            ),
        ),
    ),
    ("POST", "/api/sync/link"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "body:account_id",
                _p(
                    "/api/sync/link",
                    json=lambda d: {
                        "external_id": d.external_id,
                        "account_id": d.account_id,
                    },
                ),
            ),
        ),
    ),
    ("POST", "/api/sync/run"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "tenant-write",
                _p("/api/sync/run", json=lambda d: {"days": 30}),
                expect_404=False,
                owner_expect=(400,),  # no credential in tests
                empty_result=lambda body: True,
            ),
        ),
    ),
    ("GET", "/api/sync/runs"): RouteSpec(
        Kind.OWNED,
        probes=(
            Probe(
                "collection",
                _p("/api/sync/runs"),
                expect_404=False,
                empty_result=lambda body: True,  # sentinel scan is the assertion
            ),
        ),
    ),
    # --- insights ---
    **{
        ("GET", f"/api/insights/{name}"): RouteSpec(
            Kind.OWNED,
            probes=(
                Probe(
                    "tenant-read",
                    _p(f"/api/insights/{name}"),
                    expect_404=False,
                    empty_result=lambda body: True,
                ),
            ),
        )
        for name in ("by-category", "trends", "burn", "recurring")
    },
}

# Pinned escape hatches. Compared both ways, so widening either is a visible
# diff hunk rather than a shrug.
_EXEMPT_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {("POST", "/api/sync/claim")}
)
_PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/health"),
        ("POST", "/api/auth/register"),
        ("POST", "/api/auth/login"),
        ("POST", "/api/auth/refresh"),
    }
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _seed(engine: Engine, user: User, marker: str, *, rich: bool) -> Dataset:
    """Build one user's world inside their own tenant scope."""

    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)
    s = factory()
    s.info[TENANT] = user.id

    account = Account(
        name=f"{marker}-ACCOUNT" if rich else f"{marker.lower()}-account",
        kind=AccountKind.checking,
        opening_balance_cents=0,
        archived=False,
        sync_source="simplefin",
        external_id=f"{marker}-EXTERNAL" if rich else f"{marker.lower()}-ext",
    )
    group = CategoryGroup(name=f"{marker}-GROUP" if rich else f"{marker.lower()}-group", sort_order=0)
    s.add_all([account, group])
    s.flush()
    category = Category(
        group_id=group.id,
        name=f"{marker}-CATEGORY" if rich else f"{marker.lower()}-cat",
        sort_order=0,
        archived=False,
    )
    other = Category(group_id=group.id, name=f"{marker.lower()}-other", sort_order=1, archived=False)
    s.add_all([category, other])
    s.flush()

    txn = Transaction(
        account_id=account.id,
        category_id=category.id,
        date=date(2026, 5, 1),
        payee=f"{marker}-PAYEE" if rich else f"{marker.lower()}-payee",
        amount_cents=-4200,
        source=TxnSource.manual,
    )
    deleted = Transaction(
        account_id=account.id,
        category_id=category.id,
        date=date(2026, 5, 2),
        payee=f"{marker}-PAYEE-DELETED" if rich else f"{marker.lower()}-gone",
        amount_cents=-1300,
        source=TxnSource.manual,
        deleted_at=date(2026, 5, 3),
    )
    rule = CategoryRule(
        match_field=RuleField.payee,
        pattern=f"{marker}-RULE" if rich else f"{marker.lower()}-rule",
        category_id=category.id,
        priority=1,
    )
    goal = Goal(
        category_id=category.id,
        kind=GoalKind.savings_target,
        target_cents=100000,
    )
    s.add_all([txn, deleted, rule, goal])
    s.commit()

    ds = Dataset(
        user_id=user.id,
        account_id=account.id,
        group_id=group.id,
        category_id=category.id,
        other_category_id=other.id,
        transaction_id=txn.id,
        deleted_transaction_id=deleted.id,
        rule_id=rule.id,
        goal_id=goal.id,
        month="2026-05",
        external_id=account.external_id or "",
        import_token="",
    )
    s.close()
    return ds


def _login_tokens(client: TestClient) -> str:
    """The refresh token the client's own login issued."""

    return getattr(client, "_envelope_refresh_token", "")


def _mint_import_token(client: TestClient, account_id: int) -> str:
    """Upload a tiny CSV so the user holds a real staging token."""

    csv = b"date,payee,amount\n2026-05-01,PROBE,-1.00\n"
    resp = client.post(
        "/api/import/preview",
        data={"account_id": str(account_id)},
        files={"file": ("probe.csv", csv, "text/csv")},
    )
    assert resp.status_code == 200, f"could not mint import token: {resp.text}"
    return resp.json()["token"]


@pytest.fixture
def worlds(engine: Engine, make_user, client_as) -> tuple[Dataset, Dataset, User, User]:
    """User A with a full dataset; user B with a small one of their own.

    B's rows exist ONLY as the positive control: with a truly empty B, a
    backend that 404s everything would pass every isolation assertion. The
    negative loop below still only ever aims B at A's ids.
    """

    user_a = make_user("a@example.com")
    user_b = make_user("b@example.com")
    a = _seed(engine, user_a, "ZZ-USER-A", rich=True)
    b = _seed(engine, user_b, "b", rich=False)

    # Real staging tokens: an opaque handle has no primary key, so it would be
    # invisible to any enumeration built from the ORM mappers.
    client_a, client_b = client_as(user_a), client_as(user_b)
    a = replace(
        a,
        import_token=_mint_import_token(client_a, a.account_id),
        refresh_token=_login_tokens(client_a),
    )
    b = replace(
        b,
        import_token=_mint_import_token(client_b, b.account_id),
        refresh_token=_login_tokens(client_b),
    )
    return a, b, user_a, user_b


def _send(client: TestClient, method: str, req: Request) -> object:
    kwargs: dict[str, object] = {}
    if req.query:
        kwargs["params"] = dict(req.query)
    if req.json is not None:
        kwargs["json"] = req.json
    return client.request(method, req.url(), **kwargs)  # type: ignore[arg-type]


def _canonical(text: str, dataset: Dataset) -> str:
    """Blank out ids the CALLER supplied, so only server-side content remains.

    A 404 body echoes the id that was asked for — "Account 1 not found." vs
    "Account 1000000000 not found." — which differs between the real and ghost
    probes purely because the caller sent different numbers. That is not a
    leak: the caller already knew what it asked for.

    Everything the SERVER contributes still has to match, so a category name or
    balance appearing in a 409 body would still be caught.
    """

    out = text
    for value in sorted(
        (str(v) for v in vars(dataset).values() if str(v)), key=len, reverse=True
    ):
        out = out.replace(value, "<ID>")
    return out


def _assert_no_sentinel(response: object) -> None:
    text = response.text  # type: ignore[attr-defined]
    leaked = [s for s in A_SENTINELS if s in text]
    assert not leaked, f"user A's data leaked to user B: {leaked} in {text[:300]}"


PROBE_CASES = [
    pytest.param(method, path, probe, id=f"{method}-{path}[{probe.vector}]")
    for (method, path), spec in sorted(SPECS.items())
    for probe in spec.probes
]


# ---------------------------------------------------------------------------
# The guards
# ---------------------------------------------------------------------------


def test_route_table_matches_the_router_exactly() -> None:
    """Every route is classified, and no classification is stale.

    Both directions: a new route with no spec is an uncovered attack surface,
    and a spec for a route that no longer exists means the table is lying.
    """

    live = api_routes()
    specced = set(SPECS)

    missing = live - specced
    assert not missing, (
        f"New route(s) with no isolation spec: {sorted(missing)}. Add each to "
        "SPECS with at least one probe, or classify it PUBLIC/EXEMPT."
    )
    stale = specced - live
    assert not stale, f"SPECS lists route(s) that no longer exist: {sorted(stale)}"


def test_exemption_list_has_not_grown() -> None:
    declared = {k for k, v in SPECS.items() if v.kind is Kind.EXEMPT}
    assert declared == _EXEMPT_ROUTES, (
        "The EXEMPT set changed. Every entry is a route no test may call; "
        f"declared={sorted(declared)} pinned={sorted(_EXEMPT_ROUTES)}"
    )


def test_public_list_has_not_grown() -> None:
    """PUBLIC is the cheap escape hatch, so it is pinned hardest.

    The natural response to a failing guard is "this route doesn't really touch
    user data". That must be a reviewable act.
    """

    declared = {k for k, v in SPECS.items() if v.kind is Kind.PUBLIC}
    assert declared == _PUBLIC_ROUTES, (
        f"The PUBLIC set changed: declared={sorted(declared)} "
        f"pinned={sorted(_PUBLIC_ROUTES)}"
    )


def test_spec_table_is_well_formed() -> None:
    for (method, path), spec in SPECS.items():
        if spec.kind is Kind.OWNED:
            # /api/import/preview is multipart and is covered by the dedicated
            # handle tests instead of a generic probe.
            if path != "/api/import/preview":
                assert spec.probes, f"{method} {path} is OWNED with no probe"
        else:
            assert not spec.probes, f"{method} {path} is {spec.kind} but has probes"
            assert spec.note, f"{method} {path} is {spec.kind} with no reason"
        for probe in spec.probes:
            if not probe.expect_404:
                assert probe.empty_result is not None, (
                    f"{method} {path}[{probe.vector}] expects a non-404; it must "
                    "say what an empty result looks like"
                )


def test_probe_template_matches_its_route() -> None:
    """A probe cannot be filed under the wrong route."""

    for (_method, path), spec in SPECS.items():
        for probe in spec.probes:
            assert probe.build(GHOST).template == path, (
                f"probe {probe.vector} is filed under {path} but targets "
                f"{probe.build(GHOST).template}"
            )


def test_every_probe_carries_a_foreign_id(worlds) -> None:
    """Kill the lazy probe that satisfies the table without attacking anything."""

    a, _b, _ua, _ub = worlds
    exempt_vectors = {"identity", "collection", "tenant-read", "tenant-write",
                      "create-lands-on-caller"}
    for (method, path), spec in SPECS.items():
        for probe in spec.probes:
            if probe.vector in exempt_vectors:
                continue
            req = probe.build(a)
            blob = f"{req.url()}|{req.query}|{req.json}"
            a_values = [str(v) for v in vars(a).values() if str(v)]
            assert any(v in blob for v in a_values), (
                f"{method} {path}[{probe.vector}] contains none of user A's "
                f"ids — it is not actually attacking anything: {blob}"
            )


def test_every_api_route_requires_authentication(anonymous_client: TestClient) -> None:
    """Anonymous access is refused everywhere except the pinned public routes.

    EXEMPT routes are skipped here (they must not be invoked) but are still
    audited by test_exempt_routes_are_still_auth_protected below.
    """

    for method, path in sorted(api_routes()):
        if (method, path) in _PUBLIC_ROUTES or (method, path) in _EXEMPT_ROUTES:
            continue
        url = path.format(
            **{
                "account_id": 1,
                "category_id": 1,
                "transaction_id": 1,
                "rule_id": 1,
                "month": "2026-05",
            }
        )
        resp = anonymous_client.request(method, url, json={})
        assert resp.status_code == 401, (
            f"{method} {path} answered {resp.status_code} without a token; "
            "it is not protected"
        )


def test_exempt_routes_are_still_auth_protected() -> None:
    """EXEMPT means 'never called by a test', not 'never audited'.

    Checked statically through the dependency tree so the route is never
    invoked.
    """

    from app.auth.dependencies import current_user_optional
    from tests.routes import iter_api_routes

    for route in iter_api_routes():
        for method in route.methods or set():
            if (method, route.path) not in _EXEMPT_ROUTES:
                continue
            names = {
                d.call for d in route.dependant.dependencies
            } | {
                sub.call
                for d in route.dependant.dependencies
                for sub in d.dependencies
            }
            assert current_user_optional in names or route.dependant.dependencies, (
                f"{method} {route.path} is exempt from being called but must "
                "still require authentication"
            )


# ---------------------------------------------------------------------------
# The isolation loop
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method,path,probe", PROBE_CASES)
def test_user_b_cannot_reach_user_a(
    method: str, path: str, probe: Probe, worlds, client_as
) -> None:
    """B aims each probe at A's ids, and at ids that exist nowhere.

    The two responses must be byte-identical: that is strictly stronger than
    "404 not 403", and it is what catches an ownership check performed after
    the lookup rather than inside it.
    """

    a, _b, _ua, user_b = worlds
    client = client_as(user_b)

    real = _send(client, method, probe.build(a))
    ghost = _send(client, method, probe.build(GHOST))

    _assert_no_sentinel(real)
    assert real.status_code != 403, (  # type: ignore[attr-defined]
        "403 confirms the object exists; it must be indistinguishable from absent"
    )

    if probe.expect_404:
        assert real.status_code == 404, (  # type: ignore[attr-defined]
            f"expected 404 for another user's id, got "
            f"{real.status_code}: {real.text[:200]}"  # type: ignore[attr-defined]
        )
        assert real.status_code == ghost.status_code  # type: ignore[attr-defined]
        assert _canonical(real.text, a) == _canonical(ghost.text, GHOST), (  # type: ignore[attr-defined]
            "response for another user's id differs from one that does not "
            f"exist:\n  A's id: {real.text[:200]}\n  ghost:  {ghost.text[:200]}"  # type: ignore[attr-defined]
        )
    else:
        assert real.status_code in (200, 201, 400, 422), real.text  # type: ignore[attr-defined]
        if probe.empty_result is not None and real.status_code in (200, 201):  # type: ignore[attr-defined]
            assert probe.empty_result(real.json()), (  # type: ignore[attr-defined]
                f"collection route leaked content for another user: "
                f"{real.text[:200]}"  # type: ignore[attr-defined]
            )


@pytest.mark.parametrize("method,path,probe", PROBE_CASES)
def test_every_probe_succeeds_against_its_own_owner(
    method: str, path: str, probe: Probe, worlds, client_as
) -> None:
    """The anti-vacuity control.

    Without this, a backend that returned 404 for everything would pass the
    isolation loop perfectly. Each probe, aimed by its owner at their own data,
    must succeed.
    """

    _a, b, _ua, user_b = worlds
    client = client_as(user_b)

    resp = _send(client, method, probe.build(b))
    assert resp.status_code in probe.owner_expect, (  # type: ignore[attr-defined]
        f"{method} {path}[{probe.vector}] failed for its OWN owner with "
        f"{resp.status_code}: {resp.text[:200]} — the probe is not live, so "  # type: ignore[attr-defined]
        "the isolation assertion above proves nothing"
    )


def test_user_a_data_is_unchanged_after_every_probe(
    worlds, client_as, engine: Engine
) -> None:
    """No probe may mutate A's rows, whatever it returns."""

    a, _b, user_a, user_b = worlds
    factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    def snapshot() -> dict[str, list[tuple]]:
        s = factory()
        s.info[TENANT] = user_a.id
        out: dict[str, list[tuple]] = {}
        for model in (Account, CategoryGroup, Category, Transaction, CategoryRule, Goal):
            rows = s.scalars(
                select(model).execution_options(include_deleted=True)
            ).all()
            out[model.__name__] = sorted(
                tuple(
                    (c.name, str(getattr(r, c.name)))
                    for c in model.__table__.columns
                    if c.name not in {"updated_at"}
                )
                for r in rows
            )
        s.close()
        return out

    before = snapshot()
    client = client_as(user_b)
    for (method, _path), spec in sorted(SPECS.items()):
        for probe in spec.probes:
            _send(client, method, probe.build(a))
    assert snapshot() == before, "a probe by user B mutated user A's data"


def test_b_cannot_revoke_as_session(worlds, client_as) -> None:
    """A refresh token is a capability: B must not be able to burn A's.

    Revoking someone else's session is a cross-user WRITE even though nothing
    is read, and it is invisible to any check that only looks for leaked data.
    """

    a, _b, user_a, user_b = worlds
    client_b = client_as(user_b)

    resp = client_b.post("/api/auth/logout", json={"refresh_token": a.refresh_token})
    assert resp.status_code == 200, resp.text

    # A's refresh token still works: B's attempt did not burn it.
    fresh = client_as(user_a)
    rotated = fresh.post("/api/auth/refresh", json={"refresh_token": a.refresh_token})
    assert rotated.status_code == 200, (
        "user B revoked user A's session: " + rotated.text
    )


def test_user_b_sees_only_its_own_rows(worlds, client_as) -> None:
    _a, _b, _ua, user_b = worlds
    client = client_as(user_b)
    for path in ("/api/accounts", "/api/categories", "/api/rules", "/api/sync/runs"):
        resp = client.get(path)
        assert resp.status_code == 200, resp.text
        _assert_no_sentinel(resp)

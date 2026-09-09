"""Prove the coverage guards actually fail when a route escapes them.

A guard that passes is worthless if it would also pass with an uncovered route
present. The old soft-delete guard walked ``app.routes`` inline, which under
FastAPI 0.141 yields _IncludedRouter wrappers rather than APIRoutes — it
discovered ZERO routes and passed vacuously for the whole app. These tests
register a real route and assert each guard notices.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import APIRouter

from app.main import app
from tests import routes as route_helper


@pytest.fixture
def smuggled_route() -> Iterator[str]:
    """Register a real, unclassified /api route for the duration of a test."""

    router = APIRouter()

    @router.get("/api/smuggled-route")
    def _smuggled() -> dict[str, str]:  # pragma: no cover - never called
        return {"leaked": "everything"}

    app.include_router(router)
    try:
        yield "/api/smuggled-route"
    finally:
        # Remove it however the router stores it, so the app is left clean.
        for collection in (app.routes, app.router.routes):
            for entry in list(collection):
                inner = getattr(entry, "original_router", None)
                if inner is router or entry in getattr(router, "routes", []):
                    collection.remove(entry)
        route_helper.api_routes.cache_clear() if hasattr(
            route_helper.api_routes, "cache_clear"
        ) else None


def test_enumeration_sees_a_newly_added_route(smuggled_route: str) -> None:
    """Precondition for every guard below: the walk must find the new route."""

    assert ("GET", smuggled_route) in route_helper.api_routes(), (
        "the route enumeration did not see a newly registered route; every "
        "guard built on it is passing vacuously"
    )


def test_soft_delete_guard_fails_on_an_unclassified_route(
    smuggled_route: str,
) -> None:
    from tests.test_soft_delete import test_every_transaction_reading_route_is_covered

    with pytest.raises(AssertionError, match="not classified"):
        test_every_transaction_reading_route_is_covered()


def test_isolation_guard_fails_on_an_unspecced_route(smuggled_route: str) -> None:
    from tests.test_cross_user_isolation import (
        test_route_table_matches_the_router_exactly,
    )

    with pytest.raises(AssertionError, match="no isolation spec"):
        test_route_table_matches_the_router_exactly()


def test_guards_pass_again_once_the_route_is_gone() -> None:
    """The failures above are caused by the route, not by ambient breakage."""

    from tests.test_cross_user_isolation import (
        test_route_table_matches_the_router_exactly,
    )
    from tests.test_soft_delete import test_every_transaction_reading_route_is_covered

    test_every_transaction_reading_route_is_covered()
    test_route_table_matches_the_router_exactly()


def test_anonymous_access_to_a_new_route_is_refused(
    smuggled_route: str, anonymous_client
) -> None:
    """Default-closed: a route nobody remembered to protect is still protected.

    This is the property that makes the global dependency worth having over
    per-router ones.
    """

    resp = anonymous_client.get(smuggled_route)
    assert resp.status_code == 401, (
        f"a newly added route answered {resp.status_code} without a token"
    )

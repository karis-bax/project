"""The route enumeration must never go blind.

Every coverage guard in this suite is built on tests/routes.py. If that helper
stops finding routes — as the old inline `app.routes` walk did when FastAPI
started wrapping included routers — every guard silently passes and the suite
reports success while checking nothing.
"""

from __future__ import annotations

from app.main import app
from tests.routes import api_get_paths, api_routes


def test_enumeration_agrees_with_the_openapi_schema() -> None:
    found = {path for _method, path in api_routes()}
    documented = {p for p in app.openapi()["paths"] if p.startswith("/api")}
    assert found == documented, (
        f"route enumeration disagrees with OpenAPI: "
        f"missing={sorted(documented - found)}, extra={sorted(found - documented)}"
    )


def test_enumeration_is_not_vacuous() -> None:
    routes = api_routes()
    assert len(routes) > 30, f"only {len(routes)} routes found; the walk is blind"
    assert len(api_get_paths()) > 10
    assert ("POST", "/api/transactions/bulk-categorize") in routes
    assert ("DELETE", "/api/transactions/{transaction_id}") in routes


def test_generated_methods_are_excluded() -> None:
    assert not {m for m, _ in api_routes()} & {"HEAD", "OPTIONS"}

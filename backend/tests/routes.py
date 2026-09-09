"""One route enumeration, shared by every coverage guard.

FastAPI 0.141 / Starlette 1.6 wrap included routers in ``_IncludedRouter``
objects, so iterating ``app.routes`` no longer yields the individual APIRoute
objects for anything registered with ``include_router``. Code that walks
``app.routes`` looking for ``.path`` therefore finds almost nothing and any
guard built on it passes vacuously — which is exactly how a route added next
month would silently escape coverage.

``iter_api_routes`` recurses through the wrappers. ``test_routes_helper.py``
asserts it agrees with the OpenAPI schema, so it cannot quietly go blind again.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi.routing import APIRoute

from app.main import app

# FastAPI generates these alongside GET; they carry no handler logic.
_GENERATED_METHODS = frozenset({"HEAD", "OPTIONS"})


def _walk(routes: object) -> Iterator[APIRoute]:
    for route in routes:  # type: ignore[union-attr]
        if isinstance(route, APIRoute):
            yield route
            continue
        # _IncludedRouter (and any future wrapper) exposes the router it wraps.
        inner = getattr(route, "original_router", None)
        if inner is not None and getattr(inner, "routes", None) is not None:
            yield from _walk(inner.routes)


def iter_api_routes() -> Iterator[APIRoute]:
    """Every APIRoute the app actually serves, wrappers flattened."""

    yield from _walk(app.routes)


def api_routes() -> set[tuple[str, str]]:
    """Every (METHOD, path template) served under /api.

    Note ``path != "/api"`` is checked as well as the prefix: a router mounted
    at a bare ``/api`` with an empty route path would be missed by a
    ``startswith("/api/")`` test.
    """

    found: set[tuple[str, str]] = set()
    for route in iter_api_routes():
        path = route.path
        if path != "/api" and not path.startswith("/api/"):
            continue
        for method in (route.methods or set()) - _GENERATED_METHODS:
            found.add((method, path))
    return found


def api_get_paths() -> set[str]:
    """Every GET path template under /api."""

    return {path for method, path in api_routes() if method == "GET"}

"""Authentication dependencies and the default-closed route guard."""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from ..db import TENANT, ALL_USERS, SessionLocal
from ..models import User
from .tokens import resolve_access_token

# auto_error=False so we control the status code, body and WWW-Authenticate
# header ourselves; auto_error=True emits 403 for a missing header, which is
# the wrong code.
bearer_scheme = HTTPBearer(auto_error=False)

# Routes reachable without a token. Pinned, and compared both ways by
# tests/test_auth.py::test_public_route_list_has_not_grown, so widening this is
# a reviewable diff hunk rather than a shrug.
AUTH_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/api/health",
        "/api/auth/register",
        "/api/auth/login",
        "/api/auth/refresh",
        "/openapi.json",
        "/docs",
        "/docs/oauth2-redirect",
        "/redoc",
    }
)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_auth_db() -> Iterator[Session]:
    """Unscoped session for resolving credentials before a user is known.

    Only the auth layer may use this. It is not ``unscoped_session`` because it
    is a FastAPI dependency rather than a maintenance escape hatch, and because
    the auth tables are not owned models — the listener lets them through
    without any tenant at all. The ALL_USERS marker is belt and braces, so this
    keeps working if User ever gains owned relationships.
    """

    db = SessionLocal()
    db.info[TENANT] = ALL_USERS
    try:
        yield db
    finally:
        db.close()


def current_user_optional(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_auth_db),
) -> User | None:
    """Resolve the bearer token to a user, or None.

    Every dependency below funnels through this one, and FastAPI caches
    sub-dependency results per request, so the token is resolved exactly once
    per request even when both the global guard and a route's own
    ``get_current_user`` are in play. Overriding this single function in tests
    also redirects both.
    """

    if credentials is None or not credentials.credentials:
        return None
    return resolve_access_token(db, credentials.credentials)


def get_current_user(user: User | None = Depends(current_user_optional)) -> User:
    """The authenticated user, or 401/403."""

    if user is None:
        raise _UNAUTHENTICATED
    if not user.is_active:
        # Safe to distinguish here: the caller already proved possession of a
        # valid token for this account.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled."
        )
    return user


def require_auth(
    request: Request, user: User | None = Depends(current_user_optional)
) -> None:
    """Global guard: every route is closed unless explicitly exempted.

    Applied as an app-level dependency rather than per-router. With per-router
    ``dependencies=[...]``, the next router someone adds is unauthenticated and
    nothing complains; here a new route is protected by default and opening it
    means editing a named frozenset that shows up in review.

    Matching is on the route *template* (``request.scope["route"].path``), not
    the raw URL, so a crafted path cannot coincidentally match an exempt
    literal.
    """

    route = request.scope.get("route")
    path = getattr(route, "path", request.url.path)
    if path in AUTH_EXEMPT_PATHS:
        return
    if user is None:
        raise _UNAUTHENTICATED
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled."
        )

"""Authentication routes.

Token-based, not cookie-based: the primary client is a native Expo app, which
has no browser cookie semantics. It stores both tokens in expo-secure-store
(never AsyncStorage, which is unencrypted).

**Client contract for refresh:** rotation means a refresh token is single-use.
A client that fires N concurrent refreshes will present an already-rotated
token N-1 times, which reuse detection reads as theft and logs the user out.
Native and web clients MUST serialise refresh behind a single-flight mutex.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import tokens as token_service
from ..auth.dependencies import bearer_scheme, get_auth_db, get_current_user
from ..auth.security import (
    hash_password,
    normalize_email,
    utcnow,
    verify_password,
)
from ..models import LoginAttempt, User
from ..settings import Settings, get_settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

# One string for every credential failure. Never distinguish "no such account"
# from "wrong password" — either would be an account-existence oracle.
_INVALID_CREDENTIALS = "Invalid email or password."
_INVALID_REFRESH = "Invalid or expired refresh token."

# Web clients receive the refresh token as an httpOnly cookie instead of
# reading it from the response body. Native clients (Expo) cannot use cookie
# semantics and keep using the body, holding the token in expo-secure-store.
# One endpoint, two transports, one security model.
#
# The difference that matters: a refresh token in JavaScript-reachable storage
# is a long-lived credential an XSS can exfiltrate and replay later from
# anywhere. In an httpOnly cookie, script cannot read it at all.
REFRESH_COOKIE = "envelope_refresh"
_WEB_CLIENT_HEADER = "x-envelope-client"


def _is_web_client(request: Request) -> bool:
    return request.headers.get(_WEB_CLIENT_HEADER, "").lower() != "native"


def _set_refresh_cookie(
    response: Response, token: str, max_age_days: int, *, secure: bool
) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age_days * 24 * 60 * 60,
        path="/api/auth",
    )


def _recent_failures(db: Session, email: str, window_minutes: int) -> int:
    """Failed attempts for this email string inside the window.

    Counts the SUBMITTED address, whether or not an account exists for it. If
    this counted user rows instead, only real accounts could be throttled and
    the limiter would leak which addresses are real — 429 for a real one, 401
    for a fake — undoing the constant-time work in auth.security.
    """

    since = utcnow() - timedelta(minutes=window_minutes)
    return (
        db.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(
                LoginAttempt.email == email,
                LoginAttempt.successful.is_(False),
                LoginAttempt.created_at > since,
            )
        )
        or 0
    )


def _record_attempt(db: Session, email: str, *, successful: bool) -> None:
    """Record an attempt against the submitted address, existing or not."""

    db.add(LoginAttempt(email=email, created_at=utcnow(), successful=successful))
    db.commit()


def _prune_attempts(db: Session, window_minutes: int) -> None:
    """Keep the table self-limiting; no cron needed."""

    cutoff = utcnow() - timedelta(minutes=max(window_minutes, 24 * 60))
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < cutoff))


@router.post(
    "/register",
    response_model=schemas.RegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: schemas.RegisterRequest,
    db: Session = Depends(get_auth_db),
    settings: Settings = Depends(get_settings),
) -> schemas.RegisterResponse:
    if not settings.allow_registration:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Registration is disabled."
        )

    email = normalize_email(payload.email)
    if db.scalar(select(User).where(User.email == email)) is not None:
        # An admitted existence oracle. Mitigated by registration being off by
        # default; the alternative needs mail infrastructure that does not
        # exist here.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered.",
        )

    user = User(email=email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return schemas.RegisterResponse(user=schemas.UserRead.model_validate(user))


@router.post("/login", response_model=schemas.TokenPairResponse)
def login(
    payload: schemas.LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_auth_db),
    settings: Settings = Depends(get_settings),
) -> schemas.TokenPairResponse:
    email = normalize_email(payload.email)

    # Throttle BEFORE the user lookup, on the submitted string.
    failures = _recent_failures(db, email, settings.login_window_minutes)
    if failures >= settings.login_max_attempts:
        # The throttled attempt is deliberately NOT recorded: recording it
        # would extend the lockout indefinitely under a retrying client, and
        # the window must be able to drain.
        response.headers["Retry-After"] = str(settings.login_window_minutes * 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(settings.login_window_minutes * 60)},
        )

    user = db.scalar(select(User).where(User.email == email))
    # An inactive account takes the dummy-hash path too, so a disabled account
    # is indistinguishable from one that never existed — by body and by timing.
    usable = user.password_hash if (user is not None and user.is_active) else None
    if not verify_password(payload.password, usable):
        _record_attempt(db, email, successful=False)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_CREDENTIALS
        )

    assert user is not None  # verify_password returns False when it is None
    # Clear the failure counter so four typos then a success then one more typo
    # does not lock the user out.
    db.execute(
        delete(LoginAttempt).where(
            LoginAttempt.email == email, LoginAttempt.successful.is_(False)
        )
    )
    _prune_attempts(db, settings.login_window_minutes)
    _record_attempt(db, email, successful=True)

    pair = token_service.issue_pair(db, user)
    db.commit()
    if _is_web_client(request):
        _set_refresh_cookie(
            response,
            pair.refresh_token,
            settings.refresh_token_ttl_days,
            secure=settings.cookie_secure,
        )
    return schemas.TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/refresh", response_model=schemas.TokenPairResponse)
def refresh(
    request: Request,
    response: Response,
    payload: schemas.RefreshRequest | None = None,
    envelope_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_auth_db),
    settings: Settings = Depends(get_settings),
) -> schemas.TokenPairResponse:
    # Body first (native), then cookie (web).
    presented = (payload.refresh_token if payload and payload.refresh_token else None) or envelope_refresh
    if not presented:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH
        )
    try:
        pair = token_service.rotate(db, presented)
    except token_service.TokenError:
        # Identical response whether the token was unknown, expired, revoked,
        # or just triggered a family revocation for reuse. Telling the caller
        # "you have been logged out everywhere" confirms the token was real.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=_INVALID_REFRESH
        ) from None
    if _is_web_client(request):
        _set_refresh_cookie(
            response,
            pair.refresh_token,
            settings.refresh_token_ttl_days,
            secure=settings.cookie_secure,
        )
    return schemas.TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
    )


@router.post("/logout", response_model=schemas.LogoutResponse)
def logout(
    request: Request,
    response: Response,
    payload: schemas.LogoutRequest | None = None,
    envelope_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_auth_db),
    user: User = Depends(get_current_user),
    credentials=Depends(bearer_scheme),  # noqa: B008
) -> schemas.LogoutResponse:
    """Revoke this session's whole token family.

    An unknown refresh token still returns 200 with ``revoked: false`` — never
    404, which would confirm whether it existed.
    """

    # Both lookups are scoped to the authenticated user: a refresh token
    # belonging to somebody else must not be revocable here.
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")

    family_id: int | None = None
    presented = (
        payload.refresh_token if payload and payload.refresh_token else None
    ) or envelope_refresh
    if presented:
        family_id = token_service.family_of_refresh_token(db, presented, user.id)
    if family_id is None and credentials is not None:
        family_id = token_service.family_of_access_token(
            db, credentials.credentials, user.id
        )

    if family_id is None:
        return schemas.LogoutResponse(revoked=False)

    token_service.revoke_family(db, family_id, "logout")
    db.commit()
    return schemas.LogoutResponse(revoked=True)


@router.get("/me", response_model=schemas.UserRead)
def me(user: User = Depends(get_current_user)) -> User:
    return user

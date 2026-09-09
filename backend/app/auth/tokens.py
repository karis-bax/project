"""Issue, resolve, rotate and revoke opaque tokens.

Tokens are random 256-bit strings stored as sha256 digests. The raw value is
returned to the caller exactly once, at issue time, and never persisted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AccessToken, RefreshToken, TokenFamily, User
from ..settings import settings
from .security import (
    ACCESS_TOKEN_PREFIX,
    REFRESH_TOKEN_PREFIX,
    new_token,
    token_hash,
    utcnow,
)


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


class TokenError(Exception):
    """A token could not be resolved or rotated.

    Deliberately carries no detail about *why*. Telling a caller that a token
    was expired rather than unknown confirms it was once real.
    """


def issue_pair(db: Session, user: User, *, family: TokenFamily | None = None) -> TokenPair:
    """Mint an access+refresh pair, optionally continuing an existing family."""

    now = utcnow()
    if family is None:
        family = TokenFamily(user_id=user.id)
        db.add(family)
        db.flush()

    raw_access = new_token(ACCESS_TOKEN_PREFIX)
    raw_refresh = new_token(REFRESH_TOKEN_PREFIX)

    db.add(
        AccessToken(
            family_id=family.id,
            user_id=user.id,
            token_hash=token_hash(raw_access),
            expires_at=now + timedelta(seconds=settings.access_token_ttl_seconds),
        )
    )
    refresh = RefreshToken(
        family_id=family.id,
        user_id=user.id,
        token_hash=token_hash(raw_refresh),
        expires_at=now + timedelta(days=settings.refresh_token_ttl_days),
    )
    db.add(refresh)
    db.flush()

    return TokenPair(
        access_token=raw_access,
        refresh_token=raw_refresh,
        expires_in=settings.access_token_ttl_seconds,
    )


def resolve_access_token(db: Session, raw_token: str) -> User | None:
    """Return the bearer of a live access token, or None.

    None for every failure mode — unknown, expired, revoked, dead family,
    inactive user — so the caller cannot distinguish them.
    """

    if not raw_token.startswith(ACCESS_TOKEN_PREFIX):
        return None

    now = utcnow()
    row = db.scalar(
        select(AccessToken).where(
            AccessToken.token_hash == token_hash(raw_token),
            AccessToken.revoked_at.is_(None),
            AccessToken.expires_at > now,
        )
    )
    if row is None:
        return None

    family = db.get(TokenFamily, row.family_id)
    if family is None or family.revoked_at is not None:
        return None

    return db.get(User, row.user_id)


def revoke_family(db: Session, family_id: int, reason: str) -> None:
    """Kill a family and every live token in it.

    Both token tables carry ``family_id``, so this invalidates outstanding
    access tokens immediately rather than leaving them valid for up to their
    remaining TTL.
    """

    now = utcnow()
    family = db.get(TokenFamily, family_id)
    if family is not None and family.revoked_at is None:
        family.revoked_at = now
        family.revoked_reason = reason

    for access in db.scalars(
        select(AccessToken).where(
            AccessToken.family_id == family_id, AccessToken.revoked_at.is_(None)
        )
    ):
        access.revoked_at = now
    for refresh in db.scalars(
        select(RefreshToken).where(
            RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None)
        )
    ):
        refresh.revoked_at = now


def rotate(db: Session, raw_refresh: str) -> TokenPair:
    """Exchange a refresh token for a new pair, invalidating the old one.

    Reuse detection: presenting a token whose ``used_at`` is already set means
    either the client replayed it or someone stole it. Both are indistinguishable
    from here, so the whole family dies and the user must log in again.

    Raises ``TokenError`` for every failure, with no detail — including after a
    reuse revocation, so an attacker learns nothing from the response.
    """

    if not raw_refresh.startswith(REFRESH_TOKEN_PREFIX):
        raise TokenError

    row = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash(raw_refresh))
    )
    if row is None:
        raise TokenError

    if row.used_at is not None:
        # Replay of an already-rotated token.
        revoke_family(db, row.family_id, "reuse_detected")
        db.commit()
        raise TokenError

    now = utcnow()
    if row.revoked_at is not None or row.expires_at <= now:
        raise TokenError

    family = db.get(TokenFamily, row.family_id)
    if family is None or family.revoked_at is not None:
        raise TokenError

    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise TokenError

    # Rotate: retire the presented token and the family's live access tokens,
    # then mint a fresh pair in the same family.
    row.used_at = now
    for access in db.scalars(
        select(AccessToken).where(
            AccessToken.family_id == family.id, AccessToken.revoked_at.is_(None)
        )
    ):
        access.revoked_at = now

    pair = issue_pair(db, user, family=family)
    row.replaced_by_id = db.scalar(
        select(RefreshToken.id).where(
            RefreshToken.token_hash == token_hash(pair.refresh_token)
        )
    )
    db.commit()
    return pair


def family_of_access_token(db: Session, raw_token: str, user_id: int) -> int | None:
    """The family behind a live access token, if it belongs to ``user_id``."""

    row = db.scalar(
        select(AccessToken).where(
            AccessToken.token_hash == token_hash(raw_token),
            AccessToken.user_id == user_id,
        )
    )
    return row.family_id if row else None


def family_of_refresh_token(db: Session, raw_token: str, user_id: int) -> int | None:
    """The family behind a refresh token, if it belongs to ``user_id``.

    The ``user_id`` predicate is load-bearing, not defensive: without it, any
    authenticated user could log another user out by posting that user's
    refresh token — a cross-user write, and a denial of service invisible to
    any check that only looks for leaked data. Token tables are not
    OwnedMixin models, so the session-level tenant filter does not cover them
    and this must be explicit.
    """

    row = db.scalar(
        select(RefreshToken).where(
            RefreshToken.token_hash == token_hash(raw_token),
            RefreshToken.user_id == user_id,
        )
    )
    return row.family_id if row else None

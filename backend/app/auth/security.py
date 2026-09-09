"""Password hashing, opaque token minting, and the one clock auth uses.

Pure functions with no database and no FastAPI imports, so they are testable in
isolation and cannot create an import cycle.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# argon2id with the library defaults (t=3, m=64MiB, p=4) — roughly 20ms per
# hash on this hardware, which is the point.
_hasher = PasswordHasher()

# Burned when the submitted email has no account, so an unknown email costs the
# same argon2 work as a wrong password. Computed at import from the LIVE hasher,
# never hardcoded: a literal would silently diverge the moment the argon2
# parameters are tuned, reopening the timing gap with no test failing.
_DUMMY_HASH = _hasher.hash("envelope-timing-equalization-dummy-password")

# Wire prefixes make the token kind obvious to secret scanners, and let /refresh
# reject an access token with a string check instead of a database round-trip.
ACCESS_TOKEN_PREFIX = "env_at_"
REFRESH_TOKEN_PREFIX = "env_rt_"


def utcnow() -> datetime:
    """Naive UTC — the single clock every auth timestamp uses.

    The rest of the codebase mixes ``func.now()`` (SQLite: UTC) with
    ``datetime.now()`` (local naive); ``SyncRun`` contains both. Token expiry
    must not inherit that confusion, or tokens outside UTC live for hours too
    long or expire on issue. Naive so it compares cleanly with the DateTime
    columns already in this schema.
    """

    return datetime.now(tz=UTC).replace(tzinfo=None)


def normalize_email(value: str) -> str:
    """Lowercase and strip, so one person cannot register two accounts.

    SQLite's default collation is case-sensitive, so ``A@x.com`` and
    ``a@x.com`` would otherwise be distinct rows and the login for one would
    silently fail. Normalizing in Python rather than with ``COLLATE NOCASE``
    keeps the semantics identical after the planned move to Postgres.
    """

    return value.strip().lower()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-work verify: a missing or corrupt hash still burns a full cycle.

    Returns False rather than raising for every failure mode. A corrupt or
    deliberately-unusable ``password_hash`` (the bootstrap user carries one
    until ``scripts/set_password.py`` runs) must be a failed login, not a 500 —
    the project rule is that malformed input is 4xx, never 500.

    Note argon2-cffi's argument order is ``verify(hash, password)``, the reverse
    of passlib's. Getting it backwards fails open on some inputs.
    """

    target = password_hash if password_hash else _DUMMY_HASH
    try:
        _hasher.verify(target, password)
    except (VerificationError, InvalidHashError):
        # InvalidHashError is NOT a subclass of VerificationError; both are
        # required or an unparseable hash escapes as a 500.
        return False
    # Reject the dummy path explicitly: a caller must never authenticate by
    # matching the timing-equalization hash.
    return bool(password_hash)


def needs_rehash(password_hash: str) -> bool:
    """True when the stored hash predates the current argon2 parameters."""

    try:
        return _hasher.check_needs_rehash(password_hash)
    except (VerificationError, InvalidHashError):
        return False


def unusable_password_hash() -> str:
    """A hash no password can ever match.

    The bootstrap user is created with this so the account exists but cannot be
    logged into until ``scripts/set_password.py`` sets a real password. It is a
    valid argon2 encoding of an unguessable secret rather than a sentinel string
    like ``"!"``, so ``verify_password`` takes the normal comparison path and
    the timing is indistinguishable from any other failed login.
    """

    return _hasher.hash(secrets.token_urlsafe(64))


def new_token(prefix: str) -> str:
    """A 256-bit opaque bearer token with a scanner-friendly prefix."""

    return f"{prefix}{secrets.token_urlsafe(32)}"


def token_hash(raw_token: str) -> str:
    """What gets stored. Never persist the raw token.

    SHA-256, not argon2: a 256-bit CSPRNG token has no dictionary to defend
    against, and argon2 on the access-token path would add ~20ms to every
    authenticated request. The threat model here is the database file — which
    ``scripts/restore_drill.py`` decrypts by design — not an online guesser.
    """

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

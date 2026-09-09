"""Authentication: tokens, rotation, throttling, and the default-closed guard."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.dependencies import AUTH_EXEMPT_PATHS
from app.auth.security import utcnow
from app.models import AccessToken, LoginAttempt, RefreshToken, TokenFamily, User
from app.settings import Settings, get_settings
from app.main import app
from tests.conftest import DEFAULT_PASSWORD, override_dependencies
from tests.routes import api_routes


def _sessions(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


# ---------------------------------------------------------------------------
# login
# ---------------------------------------------------------------------------


def test_login_returns_a_token_pair(anonymous_client: TestClient, default_user) -> None:
    resp = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"].startswith("env_at_")
    assert body["refresh_token"].startswith("env_rt_")
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 900


def test_login_is_case_insensitive_on_email(
    anonymous_client: TestClient, default_user
) -> None:
    resp = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email.upper(), "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200, resp.text


def test_wrong_password_and_unknown_email_are_indistinguishable(
    anonymous_client: TestClient, default_user
) -> None:
    """Same status AND same body. Anything else is an account-existence oracle."""

    wrong = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": "not-the-password"},
    )
    unknown = anonymous_client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "not-the-password"},
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.text == unknown.text


def test_both_failure_paths_do_the_same_hashing_work(
    anonymous_client: TestClient, default_user, monkeypatch
) -> None:
    """Assert the MECHANISM, not the wall clock.

    A timing assertion would be flaky in CI and someone would eventually delete
    it. Counting argon2 verifications proves the property that produces the
    equal timing: the unknown-email path burns a full cycle against a dummy
    hash rather than returning early.
    """

    calls: list[str] = []
    import app.routers.auth as auth_router
    from app.auth import security

    real_verify = security.verify_password

    def counting_verify(password: str, password_hash: str | None) -> bool:
        # Record which hash was fed to argon2: the dummy on the unknown-email
        # path, the stored one otherwise. Both must be exactly one call.
        calls.append(password_hash or "<dummy>")
        return real_verify(password, password_hash)

    monkeypatch.setattr(auth_router, "verify_password", counting_verify)

    calls.clear()
    anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": "wrong"},
    )
    known_calls = len(calls)

    calls.clear()
    anonymous_client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "wrong"},
    )
    unknown_calls = len(calls)

    assert known_calls == unknown_calls == 1, (
        f"wrong-password did {known_calls} argon2 verifications, unknown-email "
        f"did {unknown_calls}; they must match or login leaks timing"
    )


def test_inactive_account_is_indistinguishable_at_login(
    anonymous_client: TestClient, engine: Engine, make_user
) -> None:
    user = make_user("disabled@example.com")
    with _sessions(engine)() as s:
        row = s.get(User, user.id)
        row.is_active = False
        s.commit()

    disabled = anonymous_client.post(
        "/api/auth/login",
        json={"email": "disabled@example.com", "password": DEFAULT_PASSWORD},
    )
    unknown = anonymous_client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": DEFAULT_PASSWORD},
    )
    assert disabled.status_code == 401, "403 here would confirm the account exists"
    assert disabled.text == unknown.text


# ---------------------------------------------------------------------------
# rate limiting
# ---------------------------------------------------------------------------


def test_login_is_throttled_after_five_failures(
    anonymous_client: TestClient, default_user
) -> None:
    for _ in range(5):
        resp = anonymous_client.post(
            "/api/auth/login",
            json={"email": default_user.email, "password": "wrong"},
        )
        assert resp.status_code == 401

    blocked = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": "wrong"},
    )
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After")


def test_attempts_are_recorded_for_addresses_with_no_account(
    anonymous_client: TestClient, engine: Engine
) -> None:
    """Throttling counts the SUBMITTED email, account or not.

    If attempts were keyed on a user row, only real accounts could be
    throttled, and the limiter would become a cleaner account-existence oracle
    than the login response itself: 429 means the address exists, 401 means it
    does not. Keying on the submitted string keeps them indistinguishable — and
    it is what stops the rate limiter undoing the constant-time hashing.
    """

    for _ in range(5):
        anonymous_client.post(
            "/api/auth/login",
            json={"email": "ghost@example.com", "password": "wrong"},
        )

    with _sessions(engine)() as s:
        recorded = s.scalar(
            select(func.count())
            .select_from(LoginAttempt)
            .where(LoginAttempt.email == "ghost@example.com")
        )
    assert recorded == 5, "attempts against a non-existent address were not recorded"

    blocked = anonymous_client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "wrong"}
    )
    assert blocked.status_code == 429, (
        "a non-existent address is not throttled, so 429-vs-401 reveals which "
        "addresses are real"
    )


def test_throttling_of_real_and_fake_addresses_is_indistinguishable(
    anonymous_client: TestClient, default_user
) -> None:
    for email in (default_user.email, "ghost@example.com"):
        for _ in range(5):
            anonymous_client.post(
                "/api/auth/login", json={"email": email, "password": "wrong"}
            )

    real = anonymous_client.post(
        "/api/auth/login", json={"email": default_user.email, "password": "wrong"}
    )
    fake = anonymous_client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "wrong"}
    )
    assert real.status_code == fake.status_code == 429
    assert real.text == fake.text


def test_successful_login_clears_the_failure_counter(
    anonymous_client: TestClient, default_user
) -> None:
    """Four typos then a success must not leave the account one typo from lockout."""

    for _ in range(4):
        anonymous_client.post(
            "/api/auth/login",
            json={"email": default_user.email, "password": "wrong"},
        )
    ok = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    )
    assert ok.status_code == 200

    again = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": "wrong"},
    )
    assert again.status_code == 401, "counter was not reset by the successful login"


# ---------------------------------------------------------------------------
# rotation and reuse
# ---------------------------------------------------------------------------


def test_refresh_rotates_and_invalidates_the_old_token(
    anonymous_client: TestClient, default_user
) -> None:
    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()

    rotated = anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["refresh_token"] != login["refresh_token"]


def test_reusing_a_rotated_refresh_token_revokes_the_family(
    anonymous_client: TestClient, engine: Engine, default_user
) -> None:
    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()
    second = anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    ).json()

    # Replay the first (already rotated) token.
    replay = anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    assert replay.status_code == 401

    # The whole family is dead, including the token issued by the good refresh.
    after = anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": second["refresh_token"]}
    )
    assert after.status_code == 401, "family was not revoked on reuse"

    with _sessions(engine)() as s:
        family = s.scalar(select(TokenFamily))
        assert family.revoked_at is not None
        assert family.revoked_reason == "reuse_detected"


def test_family_revocation_kills_live_access_tokens_immediately(
    anonymous_client: TestClient, default_user
) -> None:
    """Not 'within the access-token TTL' — immediately."""

    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()
    anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )  # reuse -> revoke

    me = anonymous_client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {login['access_token']}"},
    )
    assert me.status_code == 401


def test_reuse_response_is_identical_to_an_unknown_token(
    anonymous_client: TestClient, default_user
) -> None:
    """Never tell the caller 'you have been logged out everywhere'."""

    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()
    anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    reuse = anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
    )
    unknown = anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": "env_rt_never-issued"}
    )
    assert reuse.status_code == unknown.status_code == 401
    assert reuse.text == unknown.text


def test_an_access_token_is_not_accepted_as_a_refresh_token(
    anonymous_client: TestClient, default_user
) -> None:
    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()
    resp = anonymous_client.post(
        "/api/auth/refresh", json={"refresh_token": login["access_token"]}
    )
    assert resp.status_code == 401


def test_tokens_are_never_stored_in_the_clear(
    anonymous_client: TestClient, engine: Engine, default_user
) -> None:
    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()

    with _sessions(engine)() as s:
        access_hashes = [t.token_hash for t in s.scalars(select(AccessToken))]
        refresh_hashes = [t.token_hash for t in s.scalars(select(RefreshToken))]

    assert login["access_token"] not in access_hashes
    assert login["refresh_token"] not in refresh_hashes
    assert all(len(h) == 64 for h in access_hashes + refresh_hashes)


# ---------------------------------------------------------------------------
# logout / me / register
# ---------------------------------------------------------------------------


def test_logout_revokes_the_family(anonymous_client: TestClient, default_user) -> None:
    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()
    headers = {"Authorization": f"Bearer {login['access_token']}"}

    out = anonymous_client.post("/api/auth/logout", headers=headers, json={})
    assert out.status_code == 200 and out.json()["revoked"] is True

    assert anonymous_client.get("/api/auth/me", headers=headers).status_code == 401
    assert (
        anonymous_client.post(
            "/api/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )


def test_me_returns_the_caller(anonymous_client: TestClient, default_user) -> None:
    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()
    me = anonymous_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {login['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == default_user.email
    assert "password_hash" not in me.text


def test_registration_is_disabled_by_default(anonymous_client: TestClient) -> None:
    resp = anonymous_client.post(
        "/api/auth/register",
        json={"email": "new@example.com", "password": "a-long-enough-password"},
    )
    assert resp.status_code == 403


def test_registration_when_enabled(anonymous_client: TestClient) -> None:
    def _open_registration() -> Settings:
        return Settings(allow_registration=True)

    with override_dependencies({get_settings: _open_registration}):
        resp = anonymous_client.post(
            "/api/auth/register",
            json={"email": "New@Example.com", "password": "a-long-enough-password"},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["user"]["email"] == "new@example.com", "email normalized"
        # Registration is not a login: no tokens in the response.
        assert "access_token" not in resp.text

        duplicate = anonymous_client.post(
            "/api/auth/register",
            json={"email": "new@example.com", "password": "a-long-enough-password"},
        )
        assert duplicate.status_code == 409


def test_short_password_is_rejected(anonymous_client: TestClient) -> None:
    def _open_registration() -> Settings:
        return Settings(allow_registration=True)

    with override_dependencies({get_settings: _open_registration}):
        resp = anonymous_client.post(
            "/api/auth/register", json={"email": "x@example.com", "password": "short"}
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# the guard
# ---------------------------------------------------------------------------


def test_public_route_list_has_not_grown() -> None:
    """AUTH_EXEMPT_PATHS is pinned; widening it must be a visible diff."""

    assert AUTH_EXEMPT_PATHS == frozenset(
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


def test_a_body_containing_user_id_is_rejected_not_ignored(
    client: TestClient, session
) -> None:
    """Ownership comes from the session; a client that tries to set it is told."""

    resp = client.post(
        "/api/accounts",
        json={
            "name": "smuggled",
            "kind": "checking",
            "opening_balance_cents": 0,
            "user_id": 999,
        },
    )
    assert resp.status_code == 422, resp.text
    assert "user_id" in resp.text


def test_unknown_fields_are_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/accounts",
        json={
            "name": "x",
            "kind": "checking",
            "opening_balance_cents": 0,
            "not_a_field": 1,
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# dual transport: cookie for web, body for native
# ---------------------------------------------------------------------------


def test_web_client_receives_an_httponly_refresh_cookie(
    anonymous_client: TestClient, default_user
) -> None:
    resp = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 200
    cookie = resp.headers.get("set-cookie", "")
    assert "envelope_refresh=" in cookie
    assert "HttpOnly" in cookie, "script must not be able to read the refresh token"
    assert "Secure" in cookie, "must not travel over plain http in production"
    assert "samesite=lax" in cookie.lower()


def test_native_client_gets_no_cookie(
    anonymous_client: TestClient, default_user
) -> None:
    """Expo has no cookie jar; it keeps the token in expo-secure-store."""

    resp = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
        headers={"X-Envelope-Client": "native"},
    )
    assert resp.status_code == 200
    assert "envelope_refresh=" not in resp.headers.get("set-cookie", "")
    assert resp.json()["refresh_token"].startswith("env_rt_")


def test_refresh_accepts_the_cookie_with_no_body(
    anonymous_client: TestClient, default_user
) -> None:
    # TestClient speaks http, and a Secure cookie is not returned over http —
    # the same reason local development needs COOKIE_SECURE=false.
    def _dev_cookies() -> Settings:
        return Settings(cookie_secure=False)

    with override_dependencies({get_settings: _dev_cookies}):
        _refresh_round_trip(anonymous_client, default_user)


def _refresh_round_trip(anonymous_client: TestClient, default_user) -> None:
    anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    )
    # The TestClient keeps the cookie jar, so this is what the web app sends.
    rotated = anonymous_client.post("/api/auth/refresh", json={})
    assert rotated.status_code == 200, rotated.text
    assert rotated.json()["access_token"].startswith("env_at_")


def test_refresh_with_neither_body_nor_cookie_is_401(
    anonymous_client: TestClient,
) -> None:
    resp = anonymous_client.post("/api/auth/refresh", json={})
    assert resp.status_code == 401


def test_logout_clears_the_cookie(anonymous_client: TestClient, default_user) -> None:
    login = anonymous_client.post(
        "/api/auth/login",
        json={"email": default_user.email, "password": DEFAULT_PASSWORD},
    ).json()
    out = anonymous_client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {login['access_token']}"},
        json={},
    )
    assert out.status_code == 200
    assert 'envelope_refresh=""' in out.headers.get(
        "set-cookie", ""
    ) or "envelope_refresh=;" in out.headers.get("set-cookie", "")

"""Application configuration.

Uses pydantic-settings rather than bare ``os.environ`` reads for one specific
reason: ``bool(os.environ.get("ALLOW_REGISTRATION"))`` is ``True`` for the
string ``"false"``. A security default that flips open because someone wrote the
word "false" is exactly the failure this module exists to prevent. Settings are
validated at import, so a typo is a startup crash rather than an open
registration endpoint.

``frozen=True`` is deliberate: tests override the ``get_settings`` dependency
rather than mutating a global. A security config any module can reassign at
runtime is not a config.
"""

from __future__ import annotations

from pydantic import EmailStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    database_url: str = "sqlite:///./envelope.db"

    # --- auth -------------------------------------------------------------
    access_token_ttl_seconds: int = 900  # 15 minutes
    refresh_token_ttl_days: int = 30
    allow_registration: bool = False
    bootstrap_email: EmailStr | None = None

    # --- login throttling -------------------------------------------------
    login_max_attempts: int = 5
    login_window_minutes: int = 15

    # --- exposure ---------------------------------------------------------
    # /openapi.json lists every route; close it in production rather than
    # relying on status-code cleverness to hide endpoints.
    docs_enabled: bool = True

    # --- SimpleFIN --------------------------------------------------------
    # The access URL is per-user (it lives in the OS keyring, keyed by user id).
    # The env var is a single-user development fallback and must name whose
    # credential it is; see the validator below.
    simplefin_access_url: str | None = None
    simplefin_access_url_user_id: int | None = None

    @model_validator(mode="after")
    def _env_credential_must_name_its_owner(self) -> "Settings":
        if self.simplefin_access_url and self.simplefin_access_url_user_id is None:
            raise ValueError(
                "SIMPLEFIN_ACCESS_URL is set but SIMPLEFIN_ACCESS_URL_USER_ID is "
                "not. Under multi-user, a bare access URL would apply to whoever "
                "happened to call /api/sync/run. Name the owning user id, or "
                "store the credential in the keyring instead."
            )
        return self


settings = Settings()


def get_settings() -> Settings:
    """FastAPI dependency, so tests can override configuration per-test."""

    return settings

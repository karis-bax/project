"""Access-URL storage and redaction.

The SimpleFIN Access URL is a read key to the user's entire financial history.
It is stored in the OS keyring (falling back to the ``SIMPLEFIN_ACCESS_URL``
environment variable) and must NEVER be written to the database, a config file,
or any log line. ``redact`` scrubs it — and any basic-auth URL — from strings so
it cannot leak through logs or exception messages.
"""

from __future__ import annotations

import os
import re

_SERVICE = "envelope-simplefin"
_USERNAME = "access-url"
_ENV_VAR = "SIMPLEFIN_ACCESS_URL"

# Last-resort in-process store used only when no keyring backend is available.
_MEMORY: dict[str, str] = {}

# Any URL carrying inline basic-auth credentials, e.g.
# https://user:pass@bridge.simplefin.org/simplefin
_BASIC_AUTH_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s\"']+")


def store_access_url(url: str) -> None:
    try:
        import keyring

        keyring.set_password(_SERVICE, _USERNAME, url)
        return
    except Exception:
        # No keyring backend (e.g. headless CI); keep it in-process only.
        _MEMORY["url"] = url


def get_access_url() -> str | None:
    env = os.environ.get(_ENV_VAR)
    if env:
        return env
    try:
        import keyring

        value = keyring.get_password(_SERVICE, _USERNAME)
        if value:
            return value
    except Exception:
        pass
    return _MEMORY.get("url")


def has_access_url() -> bool:
    return get_access_url() is not None


def clear_access_url() -> None:
    _MEMORY.pop("url", None)
    try:
        import keyring

        keyring.delete_password(_SERVICE, _USERNAME)
    except Exception:
        pass


def redact(text: object) -> str:
    """Return ``text`` with the access URL and any basic-auth URL replaced."""

    s = "" if text is None else str(text)
    url = get_access_url()
    if url:
        s = s.replace(url, "***")
    return _BASIC_AUTH_URL.sub("***", s)

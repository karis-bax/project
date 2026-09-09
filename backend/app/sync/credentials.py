"""Per-user access-URL storage and redaction.

The SimpleFIN Access URL is a read key to one user's entire financial history.
It is stored in the OS keyring **keyed by user id**, and must NEVER be written
to the database, a config file, or any log line.

``redact`` scrubs a known URL — and any basic-auth URL — from strings so it
cannot leak through logs or exception messages.
"""

from __future__ import annotations

import re

from ..settings import settings

_SERVICE = "envelope-simplefin"

# Last-resort in-process store, used only when no keyring backend is available
# (headless CI, a container without a secret service). Keyed by user id: the
# old single ``"url"`` key meant every user shared one credential slot exactly
# where a keyring is least likely to exist.
_MEMORY: dict[int, str] = {}

# Any URL carrying inline basic-auth credentials, e.g.
# https://user:pass@bridge.simplefin.org/simplefin
_BASIC_AUTH_URL = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@]+:[^\s/@]+@[^\s\"']+")


def _username(user_id: int) -> str:
    """Keyring entry name for one user.

    Namespaced rather than a bare id so a future second secret type cannot
    collide, and so the entry is identifiable in `security find-generic-password`.
    """

    return f"user:{user_id}:access-url"


def store_access_url(user_id: int, url: str) -> None:
    try:
        import keyring

        keyring.set_password(_SERVICE, _username(user_id), url)
        return
    except Exception:
        # No keyring backend (e.g. headless CI); keep it in-process only.
        _MEMORY[user_id] = url


def get_access_url(user_id: int) -> str | None:
    """This user's access URL, or None.

    The keyring is consulted FIRST. The environment variable is a
    single-user development fallback that applies to exactly one user id, named
    by SIMPLEFIN_ACCESS_URL_USER_ID — it used to be checked first and with no
    owner, which under multi-user meant one env var silently became every
    user's credential.
    """

    try:
        import keyring

        value = keyring.get_password(_SERVICE, _username(user_id))
        if value:
            return value
    except Exception:
        pass

    if (
        settings.simplefin_access_url
        and settings.simplefin_access_url_user_id == user_id
    ):
        return settings.simplefin_access_url

    return _MEMORY.get(user_id)


def has_access_url(user_id: int) -> bool:
    return get_access_url(user_id) is not None


def clear_access_url(user_id: int) -> None:
    _MEMORY.pop(user_id, None)
    try:
        import keyring

        keyring.delete_password(_SERVICE, _username(user_id))
    except Exception:
        pass


def redact(text: object, *, url: str | None = None) -> str:
    """Return ``text`` with ``url`` and any basic-auth URL replaced.

    This never looks up a credential itself. Under multi-user a global lookup
    would scrub whoever's URL happened to be resolvable — possibly a different
    user's than the one whose error is being formatted — which is both useless
    and a reason to read a credential that is none of this call's business. The
    caller passes the URL it already holds; the regex is the always-on floor.
    """

    s = "" if text is None else str(text)
    if url:
        s = s.replace(url, "***")
    return _BASIC_AUTH_URL.sub("***", s)

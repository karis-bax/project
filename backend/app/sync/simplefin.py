"""SimpleFIN Bridge provider.

This is the ONLY module that knows SimpleFIN exists. It implements the
``SyncProvider`` protocol plus the one-time setup-token claim.

All monetary values from SimpleFIN are decimal strings (e.g. "-33.45"); they are
parsed with ``decimal.Decimal`` and quantized to integer cents. ``float()`` is
never called on them.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlencode, urlsplit, urlunsplit

from . import credentials
from .base import NormalizedAccount, NormalizedTxn, SyncError

_TIMEOUT = 30


class SetupTokenError(SyncError):
    """Raised when a setup token cannot be claimed (e.g. already used)."""


def amount_to_cents(value: str | float | int) -> int:
    """Parse a SimpleFIN decimal-string amount into signed integer cents."""

    # Decimal(str(...)) keeps exactness; never float().
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _epoch(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def _epoch_to_date(epoch: int) -> date:
    return datetime.fromtimestamp(int(epoch), tz=UTC).date()


def _split_credentials(access_url: str) -> tuple[str, str, str]:
    """Return (clean_base_url, username, password) from a basic-auth URL."""

    parts = urlsplit(access_url)
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    clean = urlunsplit((parts.scheme, host, parts.path, "", ""))
    return clean.rstrip("/"), parts.username or "", parts.password or ""


# --- setup token claim (ONE-TIME; never inside a retry loop) ----------------


def decode_setup_token(setup_token: str) -> str:
    """A setup token is a base64-encoded claim URL."""

    return base64.b64decode(setup_token).decode("utf-8").strip()


def claim_setup_token(setup_token: str) -> str:
    """POST once to the decoded claim URL and return the Access URL.

    Setup tokens are one-time. A 403 means it was already claimed. This makes a
    single POST and must never be retried.
    """

    claim_url = decode_setup_token(setup_token)
    request = urllib.request.Request(claim_url, data=b"", method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return response.read().decode("utf-8").strip()
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise SetupTokenError(
                "Setup token has already been claimed (403). Setup tokens are "
                "one-time; generate a new one from SimpleFIN."
            ) from None
        raise SetupTokenError(
            f"Could not claim setup token (HTTP {exc.code})."
        ) from None
    except urllib.error.URLError as exc:
        # Never let the reason string leak a URL/credentials.
        raise SetupTokenError(
            f"Could not reach SimpleFIN to claim the token: {credentials.redact(exc.reason)}"
        ) from None


# --- fetch ------------------------------------------------------------------


def _http_get_json(access_url: str, path: str, params: list[tuple[str, str]]) -> dict:
    """Perform an authenticated GET and return parsed JSON.

    Isolated so tests can monkeypatch it without any network access.
    """

    base, user, password = _split_credentials(access_url)
    url = f"{base}{path}?{urlencode(params)}"
    request = urllib.request.Request(url, method="GET")
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    request.add_header("Authorization", f"Basic {token}")
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return json.loads(response.read().decode("utf-8"))


def parse_account_set(data: dict) -> tuple[list[NormalizedAccount], list]:
    """Parse a SimpleFIN AccountSet into normalized accounts + errlist."""

    errlist = list(data.get("errlist", []) or [])
    accounts: list[NormalizedAccount] = []
    for acct in data.get("accounts", []) or []:
        org = acct.get("org") or {}
        balance_date = acct.get("balance-date")
        txns: list[NormalizedTxn] = []
        for t in acct.get("transactions", []) or []:
            posted = int(t.get("posted") or 0)
            pending = bool(t.get("pending")) or posted == 0
            if posted > 0:
                posted_date = _epoch_to_date(posted)
            elif t.get("transacted_at"):
                posted_date = _epoch_to_date(int(t["transacted_at"]))
            else:
                posted_date = datetime.now(tz=UTC).date()
            txns.append(
                NormalizedTxn(
                    external_id=str(t.get("id")),
                    posted_date=posted_date,
                    amount_cents=amount_to_cents(t.get("amount", "0")),
                    description=(t.get("description") or "").strip(),
                    pending=pending,
                    raw=t,
                )
            )
        accounts.append(
            NormalizedAccount(
                external_id=str(acct.get("id")),
                name=(acct.get("name") or "").strip(),
                org_name=(org.get("name") or org.get("domain") or "").strip(),
                currency=acct.get("currency") or "USD",
                balance_cents=amount_to_cents(acct.get("balance", "0")),
                balance_date=_epoch_to_date(balance_date) if balance_date else None,
                transactions=txns,
            )
        )
    return accounts, errlist


class SimpleFINProvider:
    """Implements the ``SyncProvider`` protocol against SimpleFIN Bridge."""

    def __init__(self, access_url: str) -> None:
        self._access_url = access_url
        self.errlist: list = []

    def fetch(self, since: date, until: date) -> list[NormalizedAccount]:
        params = [
            ("start-date", str(_epoch(since))),
            ("end-date", str(_epoch(until))),
            ("pending", "1"),
        ]
        try:
            data = _http_get_json(self._access_url, "/accounts", params)
        except Exception as exc:  # noqa: BLE001
            # Redact and drop the original chain so no URL/creds can surface in
            # a formatted traceback.
            raise SyncError(
                f"Failed to fetch from SimpleFIN: {credentials.redact(exc)}"
            ) from None
        accounts, errlist = parse_account_set(data)
        self.errlist = errlist
        return accounts

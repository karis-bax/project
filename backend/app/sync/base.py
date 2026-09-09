"""Provider-agnostic sync interface.

Concrete providers (SimpleFIN today; Teller/Plaid later) normalize their wire
formats into these dataclasses. Nothing outside a provider module should know
which bank aggregator is in use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Protocol


class SyncError(Exception):
    """A sync failure whose message is already redaction-safe."""


@dataclass
class NormalizedTxn:
    external_id: str
    posted_date: date
    amount_cents: int
    description: str
    pending: bool
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedAccount:
    external_id: str
    name: str
    org_name: str
    currency: str
    balance_cents: int
    balance_date: date | None
    transactions: list[NormalizedTxn] = field(default_factory=list)


class SyncProvider(Protocol):
    def fetch(self, since: date, until: date) -> list[NormalizedAccount]:
        """Fetch accounts and their transactions for the window [since, until)."""
        ...

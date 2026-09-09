"""Pure category-rule matching (no DB, no FastAPI).

A rule matches when its (case-insensitive) ``pattern`` appears as a substring of
the chosen field (payee or memo). Rules are evaluated in priority order and the
first match wins.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    match_field: str  # "payee" | "memo"
    pattern: str
    category_id: int
    priority: int


def sort_rules(rules: list[Rule]) -> list[Rule]:
    """Highest priority first; ties broken by category_id for determinism."""

    return sorted(rules, key=lambda r: (-r.priority, r.category_id))


def propose_category(
    rules_sorted: list[Rule], payee: str, memo: str
) -> int | None:
    for rule in rules_sorted:
        haystack = payee if rule.match_field == "payee" else memo
        if rule.pattern and rule.pattern.lower() in (haystack or "").lower():
            return rule.category_id
    return None

"""Shared FastAPI dependencies."""

from __future__ import annotations

import re

from fastapi import HTTPException, Path

from .db import get_db  # re-exported for routers

__all__ = ["get_db", "MONTH_RE", "validate_month", "month_path"]

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_month(value: str) -> str:
    """Return ``value`` if it is a ``YYYY-MM`` month, else raise HTTP 422."""

    if not MONTH_RE.match(value):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid month '{value}'; expected format YYYY-MM (month 01-12).",
        )
    return value


def month_path(month: str = Path(..., description="Budget month, YYYY-MM")) -> str:
    """Path dependency that validates the ``{month}`` segment (422 on malformed)."""

    return validate_month(month)

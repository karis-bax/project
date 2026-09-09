"""Shared FastAPI dependencies."""

from __future__ import annotations

import re
from typing import TypeVar

from fastapi import HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Base, get_db  # get_db re-exported for routers

__all__ = [
    "get_db",
    "get_live_or_404",
    "MONTH_RE",
    "validate_month",
    "month_path",
]

_Model = TypeVar("_Model", bound=Base)


def get_live_or_404(
    db: Session,
    model: type[_Model],
    pk: int,
    *,
    label: str | None = None,
) -> _Model:
    """Load one row by primary key through a real SELECT, or raise 404.

    Use this instead of ``db.get()`` for any model the session-level filter
    applies to. ``Session.get()`` returns an identity-map hit **without
    emitting SQL**, so ``do_orm_execute`` never fires and the filter never
    applies — it will hand back a soft-deleted row that a SELECT would have
    excluded. A statement always goes to the database, so the criteria always
    run.

    404 rather than 403: a row the caller may not see must be
    indistinguishable from a row that does not exist.
    """

    obj = db.scalar(select(model).where(model.id == pk))
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{label or model.__name__} {pk} not found.",
        )
    return obj

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

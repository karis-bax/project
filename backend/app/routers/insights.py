"""Insights aggregate endpoints. All computation happens here, not the browser."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import insights, schemas
from ..deps import get_db, validate_month

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/by-category", response_model=schemas.ByCategoryResponse)
def by_category(
    month: str | None = None,
    compare_to: str | None = None,
    db: Session = Depends(get_db),
) -> schemas.ByCategoryResponse:
    month = validate_month(month) if month else insights.current_month()
    if compare_to is not None:
        validate_month(compare_to)
    return insights.by_category(db, month, compare_to)


@router.get("/trends", response_model=schemas.TrendsResponse)
def trends(
    months: int = Query(6, ge=2, le=24),
    db: Session = Depends(get_db),
) -> schemas.TrendsResponse:
    return insights.trends(db, months)


@router.get("/burn", response_model=schemas.BurnResponse)
def burn(
    month: str | None = None, db: Session = Depends(get_db)
) -> schemas.BurnResponse:
    month = validate_month(month) if month else insights.current_month()
    return insights.burn(db, month)


@router.get("/recurring", response_model=schemas.RecurringResponse)
def recurring(db: Session = Depends(get_db)) -> schemas.RecurringResponse:
    return insights.recurring(db)

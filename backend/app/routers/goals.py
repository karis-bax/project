"""Goal routes (read-only for now)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas
from ..deps import get_db
from ..models import Goal

router = APIRouter(prefix="/api/goals", tags=["goals"])


@router.get("", response_model=list[schemas.GoalRead])
def list_goals(
    category_id: int | None = None, db: Session = Depends(get_db)
) -> list[Goal]:
    stmt = select(Goal)
    if category_id is not None:
        stmt = stmt.where(Goal.category_id == category_id)
    return list(db.scalars(stmt))

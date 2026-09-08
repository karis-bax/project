"""Health check."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter

from .. import schemas

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health", response_model=schemas.HealthResponse)
def health() -> schemas.HealthResponse:
    return schemas.HealthResponse(status="ok", time=dt.datetime.now(dt.UTC))

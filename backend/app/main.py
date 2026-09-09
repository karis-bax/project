"""Envelope FastAPI application."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth.dependencies import require_auth
from .settings import settings
from .routers import (
    accounts,
    auth,
    budget,
    categories,
    goals,
    health,
    imports,
    insights,
    rules,
    sync,
    transactions,
)

# Auth is a GLOBAL dependency with a pinned exemption set, not a per-router
# one: with per-router dependencies the next router someone adds is
# unauthenticated and nothing complains. Here every route is closed by default
# and opening one means editing AUTH_EXEMPT_PATHS, which shows up in review.
#
# The docs endpoints list every route, so close them in production rather than
# relying on status codes to hide anything.
app = FastAPI(
    title="Envelope API",
    version="0.1.0",
    dependencies=[Depends(require_auth)],
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(transactions.router)
app.include_router(budget.router)
app.include_router(goals.router)
app.include_router(rules.router)
app.include_router(imports.router)
app.include_router(sync.router)
app.include_router(insights.router)

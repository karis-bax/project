"""Envelope FastAPI application."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    accounts,
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

app = FastAPI(title="Envelope API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(transactions.router)
app.include_router(budget.router)
app.include_router(goals.router)
app.include_router(rules.router)
app.include_router(imports.router)
app.include_router(sync.router)
app.include_router(insights.router)

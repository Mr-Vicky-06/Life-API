"""Health check route — no auth required."""
from __future__ import annotations

from fastapi import APIRouter

from app.db import check_db

router = APIRouter()


@router.get("/health")
def health() -> dict:
    db_ok = check_db()
    return {"status": "ok", "db": db_ok, "llm": False}

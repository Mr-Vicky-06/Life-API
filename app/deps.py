"""FastAPI dependencies (auth, DB sessions)."""
from __future__ import annotations

import hmac

from fastapi import Depends, Header, HTTPException, status

from app.config import Settings, get_settings
from app.db import get_ro_session, get_rw_session  # noqa: F401 — re-exported


def verify_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> None:
    """Validate X-API-Key using constant-time comparison. Missing or invalid returns 401."""
    if not x_api_key or not hmac.compare_digest(x_api_key, settings.app_api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "unauthorized", "message": "Invalid or missing API key."}},
        )

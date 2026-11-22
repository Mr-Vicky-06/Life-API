"""FastAPI application entry point."""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes_health import router as health_router
from app.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------
settings = get_settings()

app = FastAPI(
    title="Life-API",
    version="0.1.0",
    docs_url="/docs" if settings.app_env == "dev" else None,
    redoc_url=None,
)

# CORS — allow only the dashboard origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Rate limiter — simple in-memory 60 req/min per API key
# ---------------------------------------------------------------------------
_rate_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 60
RATE_WINDOW = 60.0  # seconds


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if request.url.path.startswith("/v1/"):
        key = request.headers.get("X-API-Key", "__anon__")
        now = time.monotonic()
        window_start = now - RATE_WINDOW
        hits = _rate_store[key]
        # Prune old hits
        _rate_store[key] = [t for t in hits if t > window_start]
        if len(_rate_store[key]) >= RATE_LIMIT:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": {"code": "rate_limited", "message": "60 req/min exceeded."}},
            )
        _rate_store[key].append(now)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(health_router)
# Additional routers are added in later phases.

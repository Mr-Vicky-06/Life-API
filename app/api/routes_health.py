"""Health check route — no auth required."""
from __future__ import annotations

import httpx
from fastapi import APIRouter

from app.config import get_settings
from app.db import check_db

router = APIRouter()


def check_llm(llm_api_base: str, llm_model: str) -> tuple[bool, str | None]:
    """Check if Ollama service is reachable and has the configured model available."""
    target_model = llm_model.removeprefix("ollama/")
    target_base = llm_api_base.rstrip("/")
    url = f"{target_base}/api/tags"

    try:
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                return False, f"Ollama returned HTTP status {resp.status_code}"
            data = resp.json()
            models = data.get("models", [])
            model_names = [m.get("name", "") for m in models if isinstance(m, dict)]
            found = any(
                name == target_model
                or name.split(":")[0] == target_model.split(":")[0]
                for name in model_names
            )
            if not found:
                return False, f"Model '{target_model}' not found in Ollama tags"
            return True, None
    except (httpx.ConnectError, httpx.NetworkError):
        return False, f"Ollama service unavailable at {target_base}"
    except httpx.TimeoutException:
        return False, f"Ollama connection timed out at {target_base}"
    except Exception:
        # Never include secrets or stack traces in llm_detail
        return False, "Failed to connect to Ollama service"


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    db_ok = check_db()
    llm_ok, llm_detail = check_llm(settings.llm_api_base, settings.llm_model)
    router_val = "needle" if settings.router_model.lower() == "needle" else "none"

    return {
        "status": "ok",
        "db": db_ok,
        "llm": llm_ok,
        "llm_detail": llm_detail,
        "router": router_val,
    }

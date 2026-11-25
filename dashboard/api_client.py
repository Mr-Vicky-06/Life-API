"""HTTP API client for the Life-API dashboard using httpx and X-API-Key authentication."""
from __future__ import annotations

import datetime
from typing import Any

import httpx

DATA_TIMEOUT_S = 30.0
AGENT_TIMEOUT_S = 120.0
START_API_HINT = "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"


class DashboardAPIError(Exception):
    """Sanitized, user-friendly error surfaced to dashboard components."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "api_error",
        is_unreachable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.code = code
        self.is_unreachable = is_unreachable


class LifeAPIClient:
    """Thin stateless HTTP client talking strictly to the FastAPI backend."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self._transport = transport

    def _sanitize(self, text: str) -> str:
        if not text:
            return ""
        cleaned = text.splitlines()[0].strip()
        if self.api_key:
            cleaned = cleaned.replace(self.api_key, "***")
        if "Traceback" in cleaned or 'File "' in cleaned:
            return ""
        return cleaned[:160]

    def _extract_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                return self._sanitize(str(payload["error"].get("message") or ""))
        except Exception:
            pass
        return ""

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = {"X-API-Key": self.api_key}
        url = f"{self.api_url}{path}"
        try:
            with httpx.Client(timeout=timeout, transport=self._transport) as client:
                resp = client.request(
                    method,
                    url,
                    headers=headers,
                    params=params,
                    json=json_body,
                )
        except httpx.TimeoutException as exc:
            raise DashboardAPIError(
                "Request timed out while waiting for the API. Please try again.",
                status_code=504,
                code="timeout",
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            raise DashboardAPIError(
                f"API unreachable. Start it with: `{START_API_HINT}`",
                code="unreachable",
                is_unreachable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise DashboardAPIError(
                "HTTP communication error while contacting the API.",
                code="http_error",
            ) from exc

        if resp.status_code < 400:
            return resp.json()

        detail = self._extract_error_message(resp)
        if resp.status_code == 401:
            raise DashboardAPIError(
                "API key rejected, check APP_API_KEY in .env",
                status_code=401,
                code="unauthorized",
            )
        if resp.status_code == 404:
            raise DashboardAPIError(
                detail or "No data found for the selected date or resource.",
                status_code=404,
                code="not_found",
            )
        if resp.status_code == 422:
            raise DashboardAPIError(
                detail or "Invalid request parameters; check date range or filters.",
                status_code=422,
                code="validation_error",
            )
        if resp.status_code == 400:
            raise DashboardAPIError(
                detail or "Request was rejected by input validation.",
                status_code=400,
                code="bad_request",
            )
        if resp.status_code == 429:
            raise DashboardAPIError(
                "Rate limit exceeded (60 requests/min). Wait a moment and retry.",
                status_code=429,
                code="rate_limited",
            )
        raise DashboardAPIError(
            "Service temporarily unavailable (check PostgreSQL and Ollama).",
            status_code=resp.status_code,
            code="service_unavailable",
        )

    def get_metrics(
        self,
        from_date: datetime.date,
        to_date: datetime.date,
        metrics: list[str] | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        }
        if metrics:
            params["metrics"] = ",".join(metrics)
        return self._request("GET", "/v1/metrics", timeout=DATA_TIMEOUT_S, params=params)

    def get_screen_time(
        self,
        from_date: datetime.date,
        to_date: datetime.date,
    ) -> list[dict[str, Any]]:
        params = {"from": from_date.isoformat(), "to": to_date.isoformat()}
        return self._request("GET", "/v1/screen-time", timeout=DATA_TIMEOUT_S, params=params)

    def get_daily_insight(self, target_date: datetime.date | None = None) -> dict[str, Any]:
        params = {"date": target_date.isoformat()} if target_date is not None else None
        return self._request("GET", "/v1/insights/daily", timeout=DATA_TIMEOUT_S, params=params)

    def search_notes(
        self,
        query: str,
        *,
        top_k: int = 8,
        source_type: str | None = None,
        date_from: datetime.date | None = None,
        date_to: datetime.date | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"query": query, "top_k": top_k}
        if source_type:
            body["source_type"] = source_type
        if date_from is not None:
            body["date_from"] = date_from.isoformat()
        if date_to is not None:
            body["date_to"] = date_to.isoformat()
        return self._request("POST", "/v1/search", timeout=DATA_TIMEOUT_S, json_body=body)

    def post_agent_chat(
        self,
        message: str,
        *,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"message": message}
        if session_id:
            body["session_id"] = session_id
        return self._request("POST", "/v1/agent/chat", timeout=AGENT_TIMEOUT_S, json_body=body)

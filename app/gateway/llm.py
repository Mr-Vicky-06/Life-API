"""LiteLLM wrapper gateway with retries, timeout, latency logging, and cloud guard."""
from __future__ import annotations

import logging
import time
from typing import Any

import litellm
from pydantic import BaseModel

from app.config import Settings, get_settings

logger = logging.getLogger("app.gateway.llm")


class LLMResponse(BaseModel):
    content: str
    model: str
    latency_ms: float
    raw_response: dict[str, Any] | None = None


class ModelGatewayError(RuntimeError):
    """Raised when model invocation fails after retries or is disallowed."""


def call_llm(
    prompt: str,
    *,
    system: str | None = None,
    settings: Settings | None = None,
    timeout: float = 60.0,
    max_retries: int = 2,
    response_format: dict[str, Any] | None = None,
) -> LLMResponse:
    """Invoke configured LLM with retries, timeout, latency logging, and cloud guard."""
    cfg = settings or get_settings()

    model = cfg.llm_model
    if not cfg.cloud_llm_enabled and not model.startswith("ollama/"):
        raise ModelGatewayError(
            f"Cloud LLM execution disabled (CLOUD_LLM_ENABLED=false). Refusing model '{model}'."
        )

    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    models_to_try = [model]
    if cfg.llm_fallback_model:
        models_to_try.append(cfg.llm_fallback_model)

    last_error: Exception | None = None

    for target_model in models_to_try:
        if not cfg.cloud_llm_enabled and not target_model.startswith("ollama/"):
            continue

        for attempt in range(max_retries + 1):
            t0 = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {
                    "model": target_model,
                    "messages": messages,
                    "timeout": timeout,
                    "api_base": cfg.llm_api_base,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                response = litellm.completion(**kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000.0
                content = response.choices[0].message.content or ""
                logger.info(
                    "LLM call succeeded: model=%s latency=%.1fms",
                    target_model,
                    latency_ms,
                )
                return LLMResponse(
                    content=content,
                    model=target_model,
                    latency_ms=latency_ms,
                )
            except Exception as exc:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                last_error = exc
                logger.warning(
                    "LLM call failed (attempt %d/%d): model=%s latency=%.1fms error=%s",
                    attempt + 1,
                    max_retries + 1,
                    target_model,
                    latency_ms,
                    exc,
                )
                if attempt < max_retries:
                    time.sleep(0.5 * (2 ** attempt))

    raise ModelGatewayError(
        f"All LLM attempts failed. Last error: {last_error}"
    ) from last_error

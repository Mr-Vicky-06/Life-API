"""LiteLLM wrapper gateway with retries, timeout, latency logging, cloud guard, and PII masking."""
from __future__ import annotations

import logging
import time
from typing import Any

import litellm
from pydantic import BaseModel

from app.config import Settings, get_settings
from app.gateway.exceptions import ModelGatewayError
from app.gateway.pii import mask, unmask

logger = logging.getLogger("app.gateway.llm")


class LLMResponse(BaseModel):
    content: str
    model: str
    latency_ms: float
    output_tokens: int = 0
    raw_response: dict[str, Any] | None = None


def call_llm(
    prompt: str = "",
    *,
    system: str | None = None,
    messages: list[dict[str, str]] | None = None,
    settings: Settings | None = None,
    timeout: float = 60.0,
    max_retries: int = 2,
    response_format: dict[str, Any] | None = None,
    temperature: float | None = None,
) -> LLMResponse:
    """Invoke configured LLM with retries, timeout, latency logging, and PII masking."""
    cfg = settings or get_settings()

    model = cfg.llm_model
    if not cfg.cloud_llm_enabled and not model.startswith("ollama/"):
        raise ModelGatewayError(
            f"Cloud LLM execution disabled (CLOUD_LLM_ENABLED=false). Refusing model '{model}'."
        )

    # Build raw messages
    if messages is not None:
        raw_messages = [dict(m) for m in messages]
        if system and not any(m.get("role") == "system" for m in raw_messages):
            raw_messages.insert(0, {"role": "system", "content": system})
    else:
        raw_messages = []
        if system:
            raw_messages.append({"role": "system", "content": system})
        if prompt:
            raw_messages.append({"role": "user", "content": prompt})

    models_to_try = [model]
    if cfg.llm_fallback_model and cfg.llm_fallback_model != model:
        models_to_try.append(cfg.llm_fallback_model)

    last_error: Exception | None = None

    for target_model in models_to_try:
        is_cloud = not target_model.startswith("ollama/")

        if not cfg.cloud_llm_enabled and is_cloud:
            logger.warning(
                "Skipping cloud fallback model '%s' because CLOUD_LLM_ENABLED=false",
                target_model,
            )
            continue

        # Prepare outbound payload: mask PII only if target is a cloud model
        pii_mapping: dict[str, str] = {}
        if is_cloud:
            outbound_messages: list[dict[str, str]] = []
            for msg in raw_messages:
                m_content, pii_mapping = mask(
                    msg.get("content", ""),
                    mapping=pii_mapping,
                    health_id_regex=getattr(cfg, "health_id_regex", None),
                )
                outbound_messages.append({**msg, "content": m_content})
        else:
            outbound_messages = raw_messages

        for attempt in range(max_retries + 1):
            t0 = time.perf_counter()
            try:
                kwargs: dict[str, Any] = {
                    "model": target_model,
                    "messages": outbound_messages,
                    "timeout": timeout,
                }
                if target_model.startswith("ollama/"):
                    kwargs["api_base"] = cfg.llm_api_base
                    kwargs["num_ctx"] = cfg.llm_num_ctx
                else:
                    if not cfg.llm_api_base.startswith("http://127.0.0.1:11434") and not cfg.llm_api_base.startswith("http://localhost:11434"):
                        kwargs["api_base"] = cfg.llm_api_base

                if response_format:
                    kwargs["response_format"] = response_format
                if temperature is not None:
                    kwargs["temperature"] = temperature

                if target_model.startswith("ollama/"):
                    logger.info(
                        "Ollama call options: model=%s api_base=%s num_ctx=%s "
                        "format=%s temperature=%s",
                        target_model,
                        kwargs.get("api_base"),
                        kwargs.get("num_ctx"),
                        (response_format or {}).get("type"),
                        kwargs.get("temperature"),
                    )

                response = litellm.completion(**kwargs)
                latency_ms = (time.perf_counter() - t0) * 1000.0
                raw_content = response.choices[0].message.content or ""

                # Unmask inbound payload if cloud
                if is_cloud and pii_mapping:
                    final_content = unmask(raw_content, pii_mapping)
                else:
                    final_content = raw_content

                usage = getattr(response, "usage", None)
                output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0

                logger.info(
                    "LLM call succeeded: model=%s latency=%.1fms tokens=%d",
                    target_model,
                    latency_ms,
                    output_tokens,
                )
                return LLMResponse(
                    content=final_content,
                    model=target_model,
                    latency_ms=latency_ms,
                    output_tokens=output_tokens,
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
                    time.sleep(0.5 * (2**attempt))

    raise ModelGatewayError(
        f"All LLM attempts failed. Last error: {last_error}"
    )

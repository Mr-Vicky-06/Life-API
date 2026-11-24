"""Structured output extraction and validation with schema feedback retries."""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import Settings, get_settings
from app.gateway.exceptions import LLMBadOutput
from app.gateway.llm import call_llm

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_CODE_FENCE_START_RE = re.compile(r"^```(?:json)?\s*", re.MULTILINE)
_CODE_FENCE_END_RE = re.compile(r"\s*```$", re.MULTILINE)
_TRAILING_COMMA_RE = re.compile(r",\s*([\]}])")


def repair_json(raw: str) -> str:
    """Strip code fences, isolate outermost JSON bounds, and prune trailing commas."""
    if not raw:
        return ""

    cleaned = raw.strip()
    # Strip markdown code fences
    cleaned = _CODE_FENCE_START_RE.sub("", cleaned)
    cleaned = _CODE_FENCE_END_RE.sub("", cleaned).strip()

    # Isolate JSON object or array bounds
    start_brace = cleaned.find("{")
    start_bracket = cleaned.find("[")

    if start_brace != -1 and (start_bracket == -1 or start_brace < start_bracket):
        end_brace = cleaned.rfind("}")
        if end_brace != -1 and end_brace > start_brace:
            cleaned = cleaned[start_brace : end_brace + 1]
    elif start_bracket != -1:
        end_bracket = cleaned.rfind("]")
        if end_bracket != -1 and end_bracket > start_bracket:
            cleaned = cleaned[start_bracket : end_bracket + 1]

    # Remove trailing commas before closing braces/brackets
    cleaned = _TRAILING_COMMA_RE.sub(r"\1", cleaned)
    return cleaned


def call_structured(
    model_cls: type[T],
    prompt: str | list[dict[str, str]],
    *,
    system: str | None = None,
    settings: Settings | None = None,
    timeout: float = 60.0,
    max_retries: int = 1,
) -> T:
    """Invoke LLM with JSON mode, validate against model_cls, with 1 corrective retry."""
    cfg = settings or get_settings()
    schema_str = json.dumps(model_cls.model_json_schema(), indent=2)

    schema_system = (
        f"{system or ''}\n\n"
        "You must respond ONLY with valid JSON conforming strictly to this schema:\n"
        f"{schema_str}\n"
        "Do not include explanation, markdown code fences, or text outside the JSON object."
    ).strip()

    # Prepare message thread
    if isinstance(prompt, str):
        thread: list[dict[str, str]] = [{"role": "user", "content": prompt}]
    else:
        thread = list(prompt)

    last_error: Exception | None = None
    last_raw_content = ""

    for attempt in range(max_retries + 1):
        attempt_num = attempt + 1
        t_start = time.perf_counter()
        output_tokens = 0

        if attempt > 0:
            # Append feedback message for corrective retry
            error_msg = (
                f"Your previous response was not valid according to the required schema.\n"
                f"Error: {last_error}\n"
                f"Previous output snippet: {last_raw_content[:200]}\n"
                "Please return valid JSON adhering strictly to the schema."
            )
            thread.append({"role": "user", "content": error_msg})

        try:
            response = call_llm(
                prompt=thread[-1]["content"] if len(thread) == 1 else "",
                system=schema_system,
                messages=thread if len(thread) > 1 else None,
                settings=cfg,
                timeout=timeout,
                response_format={"type": "json_object"},
            )
            output_tokens = response.output_tokens
            content = response.content.strip()
            last_raw_content = content

            # Parse JSON
            try:
                parsed_json = json.loads(content)
            except json.JSONDecodeError:
                repaired = repair_json(content)
                parsed_json = json.loads(repaired)

            # Validate Pydantic schema
            validated = model_cls.model_validate(parsed_json)
            t_attempt = (time.perf_counter() - t_start) * 1000.0
            logger.info(
                "call_structured attempt=%d latency=%.1fms output_tokens=%d validation_failed=False",
                attempt_num,
                t_attempt,
                output_tokens,
            )
            return validated

        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            t_attempt = (time.perf_counter() - t_start) * 1000.0
            logger.warning(
                "call_structured attempt=%d latency=%.1fms output_tokens=%d validation_failed=True error=%s",
                attempt_num,
                t_attempt,
                output_tokens,
                exc,
            )
            if attempt < max_retries:
                # Store the model's bad output in thread for context
                thread.append({"role": "assistant", "content": last_raw_content})
        except Exception as exc:
            last_error = exc
            t_attempt = (time.perf_counter() - t_start) * 1000.0
            logger.warning(
                "call_structured attempt=%d latency=%.1fms output_tokens=%d validation_failed=True error=%s",
                attempt_num,
                t_attempt,
                output_tokens,
                exc,
            )

    raise LLMBadOutput(
        f"Model failed to produce valid structured output for {model_cls.__name__}. "
        f"Last error: {last_error}"
    )

"""Tool router interface and backends for the ReAct agent.

Provides the RouterBackend protocol and the default GeneralLLMRouter (using the
primary Ollama model through app/gateway/llm.py). NeedleRouter was evaluated in
spike_needle.py but rejected due to falling short of threshold (85.0% < 90.0%).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from app.config import Settings, get_settings
from app.gateway.llm import call_llm
from app.gateway.structured import repair_json

logger = logging.getLogger(__name__)


@runtime_checkable
class RouterBackend(Protocol):
    """Protocol for ReAct agent tool selection backends."""

    def select_tool(
        self,
        message: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Select a tool action given user message and tool definitions.

        Returns:
            Dict in the format {"thought": str (optional), "action": str, "action_input": dict}.
        """
        ...


class GeneralLLMRouter:
    """Default tool router powered by the configured general LLM via gateway/llm.py."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def select_tool(
        self,
        message: str,
        tools: list[dict[str, Any]],
        *,
        system: str | None = None,
        messages: list[dict[str, str]] | None = None,
        timeout: float = 60.0,
        raise_on_error: bool = False,
    ) -> dict[str, Any]:
        """Route to tool or final response returning thought, action, and action_input."""
        tool_names = [t.get("name") for t in tools if isinstance(t, dict)]
        sys_prompt = system or (
            "You are a tool router. Choose exactly one action from: "
            + ", ".join(str(name) for name in tool_names)
            + ', or \'final\'. Return JSON: {"thought": "...", "action": "...", '
            '"action_input": {...}}'
        )

        outbound = (
            list(messages) if messages is not None else [{"role": "user", "content": message}]
        )

        try:
            response = call_llm(
                messages=outbound,
                system=sys_prompt,
                settings=self.settings,
                timeout=timeout,
                max_retries=1,
                response_format={"type": "json_object"},
                temperature=0.0,
            )
            cleaned = repair_json(response.content or "{}")
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict) and "action" in parsed:
                raw_input = parsed.get("action_input")
                if isinstance(raw_input, dict):
                    action_input: dict[str, Any] = raw_input
                elif raw_input is None:
                    action_input = {}
                else:
                    action_input = {"_invalid_action_input": raw_input}
                return {
                    "thought": str(parsed.get("thought") or ""),
                    "action": str(parsed["action"]),
                    "action_input": action_input,
                }
            raise ValueError("Router output JSON missing 'action' field.")
        except Exception as exc:
            if raise_on_error:
                raise
            logger.warning(
                "Router selection failed (%s); falling back to final.", type(exc).__name__
            )
            return {
                "thought": "",
                "action": "final",
                "action_input": {"answer": message},
            }


def get_router(settings: Settings | None = None) -> RouterBackend:
    """Factory to acquire the configured tool router instance."""
    resolved_settings = settings or get_settings()
    router_choice = resolved_settings.router_model.lower()

    if router_choice == "needle":
        # Needle was rejected in the spike (85.0% < 90% threshold).
        raise ValueError(
            "Needle router is not enabled: accuracy spike fell below threshold "
            "(tool: 85.0% < 90.0%, args: 85.0%). Configure ROUTER_MODEL=general."
        )

    return GeneralLLMRouter(settings=resolved_settings)

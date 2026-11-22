"""Tool router interface and backends for the ReAct agent.

Provides the RouterBackend protocol and the default GeneralLLMRouter (using the
primary Ollama model). NeedleRouter was evaluated in spike_needle.py but rejected
due to falling short of the accuracy threshold (85.0% < 90.0%).
"""
from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from app.config import Settings, get_settings


@runtime_checkable
class RouterBackend(Protocol):
    """Protocol for ReAct agent tool selection backends."""

    def select_tool(
        self,
        message: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Select a tool action given user message and tool definitions.

        Args:
            message: Natural language query or user turn.
            tools: List of tool specification dictionaries.

        Returns:
            Dict in the format {"action": str, "action_input": dict}.
            If no tool is required, action should be "final" or "none".
        """
        ...


class GeneralLLMRouter:
    """Default tool router powered by the general Ollama model via LiteLLM."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def select_tool(
        self,
        message: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Route to an appropriate tool using structured prompt instructions."""
        import litellm

        tool_names = [t.get("name") for t in tools if isinstance(t, dict)]
        system_prompt = (
            "You are a tool router. Choose exactly one action from: "
            + ", ".join(tool_names)
            + ", or 'final'. Return JSON: {\"action\": \"...\", \"action_input\": {...}}"
        )

        try:
            response = litellm.completion(
                model=self.settings.llm_model,
                api_base=self.settings.llm_api_base,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": message},
                ],
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            if "action" in parsed and "action_input" in parsed:
                return {
                    "action": str(parsed["action"]),
                    "action_input": dict(parsed["action_input"]),
                }
        except Exception:
            pass

        return {"action": "final", "action_input": {"answer": message}}


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

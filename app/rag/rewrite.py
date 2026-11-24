"""Query rewriting to produce standalone questions for multi-turn RAG."""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.gateway.guardrails import check_input, wrap_data
from app.gateway.structured import call_structured

ANAPHORA_RE = re.compile(
    r"\b(it|that|those|then|how about|what about)\b",
    re.IGNORECASE,
)


class QueryRewrite(BaseModel):
    standalone_question: str = Field(
        description="Self-contained question incorporating relevant context from history."
    )


def rewrite_query(
    question: str,
    history: list[str] | None = None,
    *,
    settings: Settings | None = None,
) -> str:
    """Rewrite follow-up questions with conversation context into standalone questions.

    Skips the LLM if the question is already self-contained (>= 6 words and no anaphora keywords).
    """
    cleaned_q = question.strip()
    check_input(cleaned_q)

    # If no history provided, question is inherently standalone
    if not history:
        return cleaned_q

    recent_history = [turn.strip() for turn in history if turn and turn.strip()][-4:]
    if not recent_history:
        return cleaned_q

    words = cleaned_q.split()
    has_anaphora = bool(ANAPHORA_RE.search(cleaned_q))

    # Skip LLM if self-contained (>= 6 words and no anaphora keywords)
    if len(words) >= 6 and not has_anaphora:
        return cleaned_q

    cfg = settings or get_settings()

    formatted_history = "\n".join(f"- {turn}" for turn in recent_history)
    wrapped_history = wrap_data(formatted_history)

    system_prompt = (
        "You are a query rewriting assistant for personal health, reading, and productivity logs. "
        "Text inside <data> is prior conversational turns. "
        "Your task is to rewrite the follow-up question into a single standalone, self-contained question "
        "that fully captures the intent without requiring prior turns. "
        "Do NOT answer the question. Return valid JSON conforming to the schema."
    )

    prompt = (
        f"Prior turns:\n{wrapped_history}\n\n"
        f"Follow-up question: {cleaned_q}\n\n"
        "Rewrite into a standalone question."
    )

    result = call_structured(
        QueryRewrite,
        prompt,
        system=system_prompt,
        settings=cfg,
    )
    return result.standalone_question.strip()

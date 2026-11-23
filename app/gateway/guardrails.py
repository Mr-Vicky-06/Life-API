"""Input and output safety guardrails."""
from __future__ import annotations

import re

from app.gateway.exceptions import GuardrailBlocked
from app.gateway.pii import redact_all

INJECTION_PHRASES = [
    "ignore previous",
    "system prompt",
    "reveal your instructions",
    "you are now",
]

_INJECTION_RE = re.compile(
    r"\b(" + "|".join(re.escape(phrase) for phrase in INJECTION_PHRASES) + r")\b",
    re.IGNORECASE,
)


def check_input(text: str, max_length: int = 4000) -> None:
    """Validate user input against length and prompt injection guardrails.

    Raises:
        GuardrailBlocked: If text is empty, exceeds max_length, or contains injection keywords.
    """
    if not text or not text.strip():
        raise GuardrailBlocked("Input cannot be empty or whitespace only.")

    if len(text) > max_length:
        raise GuardrailBlocked(
            f"Input length ({len(text)}) exceeds maximum allowed ({max_length})."
        )

    match = _INJECTION_RE.search(text)
    if match:
        raise GuardrailBlocked(
            f"Input contains disallowed prompt injection pattern: '{match.group(0)}'."
        )


def wrap_data(text: str) -> str:
    """Wrap untrusted retrieved note or observation text in <data> tags."""
    if not text:
        return "<data></data>"
    return f"<data>{text}</data>"


def check_output(
    text: str,
    system_prompt: str | None = None,
    literal_secrets: list[str] | None = None,
) -> str:
    """Sanitize output by stripping secret patterns and preventing system prompt leaks.

    Args:
        text: Raw generated output text.
        system_prompt: Optional active system prompt to check against leakage.
        literal_secrets: Optional list of literal secret strings to redact.

    Returns:
        Sanitized output string.
    """
    if not text:
        return ""

    # 1. Strip secret patterns and literal tokens
    sanitized = redact_all(text, literal_secrets=literal_secrets)

    # 2. Check for system prompt leakage
    if system_prompt and len(system_prompt) > 20:
        # Check if a substantial snippet (>40 chars) of system prompt is verbatim in output
        clean_prompt = system_prompt.strip()
        snippet = clean_prompt[:min(50, len(clean_prompt))]
        if snippet in sanitized:
            return "I cannot disclose internal system prompt instructions."

    return sanitized

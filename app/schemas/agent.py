"""Pydantic schemas for ReAct agent chat endpoint (/v1/agent/chat)."""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=800)
    session_id: str | None = None

    @field_validator("message")
    @classmethod
    def _validate_non_empty_message(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("message must not be empty or whitespace only.")
        return value

    @field_validator("session_id")
    @classmethod
    def _validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not SESSION_ID_PATTERN.fullmatch(value):
            raise ValueError("session_id must match [A-Za-z0-9_-]{1,64}.")
        return value


class AgentStep(BaseModel):
    thought: str = ""
    action: Literal["sql_query", "search_notes", "get_metrics", "final"]
    action_input: dict[str, Any]
    observation: str | None = None


class AgentResponse(BaseModel):
    answer: str
    steps: list[AgentStep]
    model: str
    session_id: str | None = None

"""Live Ollama verification test for structured output."""
from __future__ import annotations

import pytest
from pydantic import BaseModel, Field

from app.gateway.structured import call_structured


class LiveMetricSummary(BaseModel):
    summary: str
    items_analyzed: int = Field(ge=0)
    sentiment: str


@pytest.mark.live
def test_live_ollama_call_structured():
    """Verify real llama3.1:8b generates valid structured output conforming to schema."""
    prompt = (
        "Analyze this note: 'Completed 5 pull requests today and slept 8 hours. Feeling great.' "
        "Return the summary, number of items analyzed (5), and sentiment (positive)."
    )

    result = call_structured(LiveMetricSummary, prompt)

    assert isinstance(result, LiveMetricSummary)
    assert len(result.summary) > 0
    assert result.items_analyzed == 5
    assert "positive" in result.sentiment.lower()

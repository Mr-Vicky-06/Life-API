"""Tests for structured output parsing, repair_json, and schema validation."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from pydantic import BaseModel, Field

from app.gateway.exceptions import LLMBadOutput
from app.gateway.llm import LLMResponse
from app.gateway.structured import call_structured, repair_json


class SampleAnalysis(BaseModel):
    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)


def test_repair_json_strips_markdown_and_trailing_commas():
    raw = """
    Here is the requested JSON output:
    ```json
    {
        "category": "Health",
        "confidence": 0.95,
        "tags": ["sleep", "recovery",],
    }
    ```
    I hope this helps!
    """
    repaired = repair_json(raw)
    assert repaired.startswith("{")
    assert repaired.endswith("}")
    assert ",]" not in repaired
    assert repair_json("") == ""


def test_call_structured_success():
    class TestModel(BaseModel):
        status: str
        count: int

    mock_resp = LLMResponse(
        content='{"status": "ok", "count": 42}',
        model="ollama/llama3.1:8b",
        latency_ms=120.0,
    )

    with patch("app.gateway.structured.call_llm", return_value=mock_resp):
        res = call_structured(TestModel, "Provide status and count.")
        assert isinstance(res, TestModel)
        assert res.status == "ok"
        assert res.count == 42


def test_call_structured_retries_on_validation_error_and_succeeds():
    class TestModel(BaseModel):
        score: int

    bad_resp = LLMResponse(
        content='{"score": "not_an_int"}',
        model="ollama/llama3.1:8b",
        latency_ms=100.0,
    )
    good_resp = LLMResponse(
        content='{"score": 99}',
        model="ollama/llama3.1:8b",
        latency_ms=110.0,
    )

    with patch("app.gateway.structured.call_llm", side_effect=[bad_resp, good_resp]) as mock_call:
        res = call_structured(TestModel, "Give score.", max_retries=1)
        assert res.score == 99
        assert mock_call.call_count == 2


def test_call_structured_raises_llm_bad_output_on_persistent_failure():
    class TestModel(BaseModel):
        required_val: int

    invalid_resp = LLMResponse(
        content="I cannot format this as JSON for you.",
        model="ollama/llama3.1:8b",
        latency_ms=90.0,
    )

    with patch("app.gateway.structured.call_llm", return_value=invalid_resp):
        with pytest.raises(LLMBadOutput) as exc_info:
            call_structured(TestModel, "Give value.", max_retries=1)

        assert "failed to produce valid structured output" in str(exc_info.value).lower()
        assert exc_info.value.code == "llm_bad_output"
        assert exc_info.value.status_code == 502

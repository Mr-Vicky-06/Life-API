"""Tests for PII masking, unmasking, and cloud guard."""
from __future__ import annotations

import json
import pytest
import respx
from httpx import Response

from app.config import Settings
from app.gateway.exceptions import ModelGatewayError
from app.gateway.llm import call_llm
from app.gateway.pii import mask, redact_all, unmask


def _build_test_secrets():
    token_gh = "gh" + "p_" + "a" * 25
    token_sk = "s" + "k-" + "b" * 20
    token_aiza = "AI" + "za" + "c" * 22
    email = "researcher@example.com"
    phone = "+1 555-123-4567"
    geo = "37.7749, -122.4194"
    return token_gh, token_sk, token_aiza, email, phone, geo


def test_mask_and_unmask_entities():
    token_gh, token_sk, token_aiza, email, phone, geo = _build_test_secrets()
    text = (
        f"Contact {email} at {phone} or visit {geo}. "
        f"Tokens: {token_gh}, {token_sk}, {token_aiza}."
    )

    masked, mapping = mask(text)

    # Assert entities masked
    assert email not in masked
    assert phone not in masked
    assert geo not in masked
    assert token_gh not in masked
    assert token_sk not in masked
    assert token_aiza not in masked

    assert "[EMAIL_1]" in masked
    assert "[PHONE_1]" in masked
    assert "[GEO_1]" in masked
    assert "[TOKEN_1]" in masked
    assert "[TOKEN_2]" in masked
    assert "[TOKEN_3]" in masked

    # Assert unmasking restores original text exactly
    unmasked = unmask(masked, mapping)
    assert unmasked == text


def test_mask_idempotency_same_value_same_placeholder():
    _, _, _, email, _, _ = _build_test_secrets()
    text = f"Primary: {email}. Secondary confirmation to {email}."

    masked, mapping = mask(text)
    assert masked.count("[EMAIL_1]") == 2
    assert "[EMAIL_2]" not in masked
    assert len(mapping) == 1
    assert mapping["[EMAIL_1]"] == email


def test_mask_health_id_custom_regex():
    hid_regex = r"\bHID-\d{6}\b"
    text = "Patient record HID-123456 verified."
    masked, mapping = mask(text, health_id_regex=hid_regex)

    assert "HID-123456" not in masked
    assert "[HEALTH_ID_1]" in masked
    assert mapping["[HEALTH_ID_1]"] == "HID-123456"

    unmasked = unmask(masked, mapping)
    assert unmasked == text


def test_unmask_unknown_placeholders_left_as_is():
    text = "Hello [EMAIL_99] and [UNKNOWN_TOKEN]."
    mapping = {"[EMAIL_1]": "alice@example.com"}
    unmasked = unmask(text, mapping)
    assert unmasked == text


def test_cloud_llm_disabled_guard():
    settings = Settings(
        cloud_llm_enabled=False,
        llm_model="openai/gpt-4o",
    )
    with pytest.raises(ModelGatewayError) as exc_info:
        call_llm("test prompt", settings=settings)

    assert "Cloud LLM execution disabled" in str(exc_info.value)


@respx.mock
def test_cloud_llm_outbound_pii_masked_and_inbound_unmasked(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "mock-test-key")
    token_gh, _, _, email, phone, _ = _build_test_secrets()
    prompt = f"Summarize request from {email} with key {token_gh}."

    settings = Settings(
        cloud_llm_enabled=True,
        llm_model="openai/gpt-4o",
    )

    # Mock OpenAI API endpoint called by litellm
    mock_route = respx.post("https://api.openai.com/v1/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1234567890,
                "model": "gpt-4o",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "Received request for [EMAIL_1] with token [TOKEN_1]. Everything looks good.",
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )
    )

    response = call_llm(prompt, settings=settings)

    # Verify that the captured HTTP request payload had ZERO emails and ZERO tokens
    assert mock_route.called
    captured_request = mock_route.calls.last.request
    body_text = captured_request.content.decode("utf-8")

    assert email not in body_text
    assert token_gh not in body_text
    assert "[EMAIL_1]" in body_text
    assert "[TOKEN_1]" in body_text

    # Verify that the response returned to the caller was unmasked back to original values
    assert email in response.content
    assert token_gh in response.content

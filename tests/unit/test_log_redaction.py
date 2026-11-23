"""Tests for root logger secret and PII redaction filter."""
from __future__ import annotations

import io
import logging

from app.gateway.logging_filter import RedactingFilter


def _build_test_secrets():
    token_gh = "gh" + "p_" + "a" * 25
    token_sk = "s" + "k-" + "b" * 20
    literal_app_key = "secret_app_key_12345"
    email = "admin@example.org"
    phone = "+1 555-987-6543"
    return token_gh, token_sk, literal_app_key, email, phone


def test_redacting_filter_sanitizes_records():
    token_gh, token_sk, literal_app_key, email, phone = _build_test_secrets()

    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    test_logger = logging.getLogger("test_redaction_logger")
    test_logger.setLevel(logging.INFO)
    test_logger.propagate = False
    test_logger.addHandler(handler)

    r_filter = RedactingFilter(literal_secrets=[literal_app_key])
    test_logger.addFilter(r_filter)

    test_logger.info("User %s with phone %s accessed resource.", email, phone)
    test_logger.info("Tokens: %s, %s, and key %s", token_gh, token_sk, literal_app_key)

    output = log_stream.getvalue()

    assert email not in output
    assert phone not in output
    assert token_gh not in output
    assert token_sk not in output
    assert literal_app_key not in output

    assert "[REDACTED]" in output

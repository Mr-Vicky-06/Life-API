"""Gateway exceptions with standardized error codes."""
from __future__ import annotations

from fastapi import HTTPException, status


class GatewayException(HTTPException):
    """Base exception for gateway errors formatted per API_SPEC."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(
            status_code=status_code,
            detail={"error": {"code": code, "message": message}},
        )


class GuardrailBlocked(GatewayException):
    """Raised when user input violates input safety guardrails."""

    def __init__(self, message: str = "Input blocked by safety guardrails.") -> None:
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="guardrail_blocked",
            message=message,
        )


class LLMBadOutput(GatewayException):
    """Raised when LLM output cannot be parsed into the required schema."""

    def __init__(self, message: str = "Model output failed schema validation.") -> None:
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="llm_bad_output",
            message=message,
        )


class LLMUnavailable(GatewayException):
    """Raised when LLM service is unreachable or timing out."""

    def __init__(self, message: str = "LLM service is currently unavailable.") -> None:
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="llm_unavailable",
            message=message,
        )


class ModelGatewayError(GatewayException):
    """Raised when model invocation fails or is disallowed by policy."""

    def __init__(self, message: str = "Model invocation failed.") -> None:
        super().__init__(
            status_code=status.HTTP_502_BAD_GATEWAY,
            code="model_gateway_error",
            message=message,
        )


class SQLRejected(GatewayException):
    """Raised when generated SQL fails security or allowlist validation."""

    def __init__(self, message: str = "Generated SQL failed safety validation.") -> None:
        super().__init__(
            status_code=422,
            code="sql_rejected",
            message=message,
        )


class SQLFailed(GatewayException):
    """Raised when validated SQL fails database execution after repair attempt."""

    def __init__(self, message: str = "SQL execution failed.") -> None:
        super().__init__(
            status_code=422,
            code="sql_failed",
            message=message,
        )


class ValidationError(GatewayException):
    """Raised when request query parameters fail validation rules."""

    def __init__(self, message: str) -> None:
        super().__init__(
            status_code=422,
            code="validation_error",
            message=message,
        )


class NotFoundError(GatewayException):
    """Raised when a requested resource has no matching data."""

    def __init__(self, message: str = "Requested resource was not found.") -> None:
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            code="not_found",
            message=message,
        )

"""Logging redaction filter for root logger."""
from __future__ import annotations

import logging
from typing import Any

from app.config import Settings, get_settings
from app.gateway.pii import redact_all

logger = logging.getLogger(__name__)


class RedactingFilter(logging.Filter):
    """Logging filter that sanitizes secrets and PII from all log messages."""

    def __init__(
        self,
        literal_secrets: list[str] | None = None,
        health_id_regex: str | None = None,
    ) -> None:
        super().__init__()
        self.literal_secrets = [s for s in (literal_secrets or []) if s and len(s) >= 4]
        self.health_id_regex = health_id_regex

    def _redact(self, item: Any) -> Any:
        if isinstance(item, str):
            return redact_all(
                item,
                literal_secrets=self.literal_secrets,
                health_id_regex=self.health_id_regex,
            )
        return item

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._redact(record.msg)

        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._redact(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._redact(v) for v in record.args)
            elif isinstance(record.args, list):
                record.args = [self._redact(v) for v in record.args]

        return True


def install_logging_redaction(settings: Settings | None = None) -> None:
    """Attach RedactingFilter to the root logger and all attached handlers."""
    cfg = settings or get_settings()
    literal_secrets = [cfg.app_api_key]
    if cfg.github_token:
        literal_secrets.append(cfg.github_token)

    redacting_filter = RedactingFilter(
        literal_secrets=literal_secrets,
        health_id_regex=cfg.health_id_regex,
    )

    root = logging.getLogger()
    # Add to root logger
    root.addFilter(redacting_filter)

    # Also add to all existing handlers on root
    for handler in root.handlers:
        handler.addFilter(redacting_filter)

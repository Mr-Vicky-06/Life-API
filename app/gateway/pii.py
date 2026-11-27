"""PII masking, unmasking, and secret redaction utilities."""
from __future__ import annotations

import os
import re
from re import Pattern

# ---------------------------------------------------------------------------
# Precompiled Regexes per docs/SECURITY.md §2
# ---------------------------------------------------------------------------
# 1. GitHub Tokens: Personal and fine-grained tokens followed by 20+ alphanumeric chars
GH_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")

# 2. API Keys: Service provider keys (OpenAI-style, Google-style, etc.)
API_KEY_SK_RE = re.compile(r"\bs[k]-[A-Za-z0-9]{16,}\b")
API_KEY_AIZA_RE = re.compile(r"\bA[I]za[0-9A-Za-z_-]{20,}\b")

# 3. Emails: standard RFC-compliant subset
EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)

# 4. Geocoordinates: lat, long
GEO_RE = re.compile(r"-?\d{1,3}\.\d{4,},\s*-?\d{1,3}\.\d{4,}")

# 5. Phone numbers: 10-13 digits with optional +, spaces, dashes, excluding dates (YYYY-MM-DD)
# Matches phone candidates; post-checked for digit count between 10 and 13.
PHONE_CANDIDATE_RE = re.compile(
    r"(?<![\w\d])(?!\d{4}-\d{2}-\d{2})"
    r"(\+?\d{1,4}[- ]?)?"
    r"(?:\(?\d{2,5}\)?[- ]?)?"
    r"\d{2,5}[- ]?\d{2,5}"
    r"(?![\w\d])"
)


def _get_health_id_re(custom_regex: str | None = None) -> Pattern[str] | None:
    regex_str = custom_regex or os.getenv("HEALTH_ID_REGEX")
    if regex_str and regex_str.strip():
        try:
            return re.compile(regex_str.strip())
        except re.error:
            return None
    return None


def mask(
    text: str,
    mapping: dict[str, str] | None = None,
    *,
    health_id_regex: str | None = None,
) -> tuple[str, dict[str, str]]:
    """Mask PII entities in text with deterministic placeholders within a request.

    Args:
        text: Text to be masked.
        mapping: Optional existing {placeholder: original_value} mapping to reuse.
        health_id_regex: Optional custom regex pattern for health IDs.

    Returns:
        (masked_text, mapping): Tuple of masked string and mapping dict.
    """
    if not text:
        return "", mapping if mapping is not None else {}

    res_mapping: dict[str, str] = dict(mapping) if mapping is not None else {}
    val_to_placeholder: dict[str, str] = {v: k for k, v in res_mapping.items()}

    # Initialize counters based on existing placeholders in mapping
    counts: dict[str, int] = {
        "EMAIL": 0,
        "PHONE": 0,
        "TOKEN": 0,
        "GEO": 0,
        "HEALTH_ID": 0,
    }
    for placeholder in res_mapping:
        match = re.match(r"\[([A-Z_]+)_(\d+)\]", placeholder)
        if match:
            p_type, idx_str = match.groups()
            idx = int(idx_str)
            if p_type in counts and idx > counts[p_type]:
                counts[p_type] = idx

    def get_or_create_placeholder(val: str, p_type: str) -> str:
        if val in val_to_placeholder:
            return val_to_placeholder[val]
        counts[p_type] += 1
        p = f"[{p_type}_{counts[p_type]}]"
        val_to_placeholder[val] = p
        res_mapping[p] = val
        return p

    masked = text

    # Pass 1: Optional Health ID
    health_re = _get_health_id_re(health_id_regex)
    if health_re:
        masked = health_re.sub(
            lambda m: get_or_create_placeholder(m.group(0), "HEALTH_ID"), masked
        )

    # Pass 2: GitHub Tokens & API Keys -> [TOKEN_n]
    masked = GH_TOKEN_RE.sub(
        lambda m: get_or_create_placeholder(m.group(0), "TOKEN"), masked
    )
    masked = API_KEY_SK_RE.sub(
        lambda m: get_or_create_placeholder(m.group(0), "TOKEN"), masked
    )
    masked = API_KEY_AIZA_RE.sub(
        lambda m: get_or_create_placeholder(m.group(0), "TOKEN"), masked
    )

    # Pass 3: Email -> [EMAIL_n]
    masked = EMAIL_RE.sub(
        lambda m: get_or_create_placeholder(m.group(0), "EMAIL"), masked
    )

    # Pass 4: Geocoordinates -> [GEO_n]
    masked = GEO_RE.sub(
        lambda m: get_or_create_placeholder(m.group(0), "GEO"), masked
    )

    # Pass 5: Phone -> [PHONE_n] (validate 10..13 digits)
    def phone_repl(m: re.Match[str]) -> str:
        match_str = m.group(0)
        digits = re.sub(r"\D", "", match_str)
        if 10 <= len(digits) <= 13:
            return get_or_create_placeholder(match_str, "PHONE")
        return match_str

    masked = PHONE_CANDIDATE_RE.sub(phone_repl, masked)

    return masked, res_mapping


def unmask(text: str, mapping: dict[str, str]) -> str:
    """Restore masked placeholders back to their original values.

    Placeholders not present in the mapping remain unchanged.
    """
    if not text or not mapping:
        return text

    # Sort placeholders by length descending to avoid partial string replacements
    sorted_placeholders = sorted(
        mapping.keys(), key=lambda p: (len(p), p), reverse=True
    )

    unmasked = text
    for placeholder in sorted_placeholders:
        unmasked = unmasked.replace(placeholder, mapping[placeholder])

    return unmasked


def redact_all(
    text: str,
    literal_secrets: list[str] | None = None,
    health_id_regex: str | None = None,
) -> str:
    """Redact all secret patterns and literal values with '[REDACTED]'.

    Used by logging filters and output guardrails.
    """
    if not text:
        return ""

    redacted = text

    # 1. Literal secret values (e.g. APP_API_KEY, GITHUB_TOKEN)
    if literal_secrets:
        for secret in literal_secrets:
            if secret and len(secret) >= 4:
                redacted = redacted.replace(secret, "[REDACTED]")

    # 2. Token patterns
    redacted = GH_TOKEN_RE.sub("[REDACTED]", redacted)
    redacted = API_KEY_SK_RE.sub("[REDACTED]", redacted)
    redacted = API_KEY_AIZA_RE.sub("[REDACTED]", redacted)

    # 3. Optional Health ID
    health_re = _get_health_id_re(health_id_regex)
    if health_re:
        redacted = health_re.sub("[REDACTED]", redacted)

    # 4. Email
    redacted = EMAIL_RE.sub("[REDACTED]", redacted)

    # 5. Geocoordinates
    redacted = GEO_RE.sub("[REDACTED]", redacted)

    # 6. Phone numbers
    def phone_repl(m: re.Match[str]) -> str:
        match_str = m.group(0)
        digits = re.sub(r"\D", "", match_str)
        if 10 <= len(digits) <= 13:
            return "[REDACTED]"
        return match_str

    redacted = PHONE_CANDIDATE_RE.sub(phone_repl, redacted)

    return redacted

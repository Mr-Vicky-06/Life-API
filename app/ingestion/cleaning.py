"""Text and row cleaning utilities."""
from __future__ import annotations

import datetime
import hashlib
import re
import zoneinfo
from typing import Any

# Regex for block HTML tags vs inline tags
_BLOCK_TAG_RE = re.compile(
    r"<\/?(?:p|div|br|hr|h[1-6]|li|tr|td|th|blockquote|pre|table)[^>]*>",
    re.IGNORECASE,
)
_INLINE_TAG_RE = re.compile(r"<[^>]+>")

# Markdown syntax patterns (accounting for optional leading indentation)
_MD_LINK_RE = re.compile(r"!?\[(.*?)\]\([^)]*\)")
_MD_HEADER_RE = re.compile(r"^[ \t]*#+[ \t]*", re.MULTILINE)
_MD_BLOCKQUOTE_RE = re.compile(r"^[ \t]*>[ \t]*", re.MULTILINE)
_MD_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[\*\-\+]|\d+\.)[ \t]+", re.MULTILINE)
_MD_BOLD_ITALIC_RE = re.compile(r"(\*\*|__|\*|_)(.*?)\1")
_MD_INLINE_CODE_RE = re.compile(r"`{1,3}(.*?)`{1,3}")
_MD_HR_RE = re.compile(r"^[ \t]*[-*_]{3,}[ \t]*$", re.MULTILINE)
_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Strip HTML tags, collapse Markdown syntax, and collapse whitespace."""
    if not text:
        return ""
    # Replace block HTML with space
    t = _BLOCK_TAG_RE.sub(" ", text)
    # Strip remaining inline HTML tags
    t = _INLINE_TAG_RE.sub("", t)
    # Collapse Markdown links and images to text label
    t = _MD_LINK_RE.sub(r"\1", t)
    # Strip headers, blockquotes, list markers, horizontal rules
    t = _MD_HEADER_RE.sub("", t)
    t = _MD_BLOCKQUOTE_RE.sub("", t)
    t = _MD_LIST_ITEM_RE.sub("", t)
    t = _MD_HR_RE.sub("", t)
    # Strip bold / italic markers and backticks
    t = _MD_BOLD_ITALIC_RE.sub(r"\2", t)
    t = _MD_INLINE_CODE_RE.sub(r"\1", t)
    # Collapse whitespace
    t = _WHITESPACE_RE.sub(" ", t).strip()
    return t


def drop_empty_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop rows where all values are None or whitespace only."""
    cleaned = []
    for row in rows:
        has_content = False
        for val in row.values():
            if val is not None and str(val).strip() != "":
                has_content = True
                break
        if has_content:
            cleaned.append(row)
    return cleaned


def parse_timestamp(
    ts_val: str | datetime.datetime, app_timezone: str = "Asia/Kolkata"
) -> datetime.datetime:
    """Parse timestamps with timezone -> UTC. Naive timestamps assumed APP_TIMEZONE."""
    tz = zoneinfo.ZoneInfo(app_timezone)
    if isinstance(ts_val, datetime.datetime):
        dt = ts_val
    else:
        s = ts_val.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(datetime.UTC)


def compute_content_hash(content: str) -> str:
    """Compute SHA-256 hash of cleaned content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

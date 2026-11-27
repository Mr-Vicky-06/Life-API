"""Unit tests for text cleaning and timestamp parsing."""
from __future__ import annotations

import datetime

from app.ingestion.cleaning import (
    clean_text,
    compute_content_hash,
    drop_empty_rows,
    parse_timestamp,
)
from app.rag.chunking import chunk_note_content


def test_clean_text_strips_html():
    raw = "<p>This is <strong>important</strong> text with a <a href='https://example.com'>link</a>.</p>"
    expected = "This is important text with a link."
    assert clean_text(raw) == expected


def test_clean_text_collapses_markdown():
    raw = """
    # Section Header
    This is **bold** text and *italic* text.
    Here is some `inline code` and a [Markdown Link](https://github.com).
    > A wise blockquote
    - List item 1
    - List item 2
    """
    cleaned = clean_text(raw)
    assert "#" not in cleaned
    assert "**" not in cleaned
    assert "`" not in cleaned
    assert "https://github.com" not in cleaned
    assert "Markdown Link" in cleaned
    assert "Section Header" in cleaned
    assert "List item 1" in cleaned


def test_clean_text_collapses_whitespace():
    raw = "Multiple    spaces \n\n and \t newlines   should be single space."
    assert clean_text(raw) == "Multiple spaces and newlines should be single space."


def test_drop_empty_rows():
    rows = [
        {"a": "hello", "b": "world"},
        {"a": "   ", "b": None},
        {"a": "", "b": ""},
        {"a": "valid", "b": ""},
    ]
    cleaned = drop_empty_rows(rows)
    assert len(cleaned) == 2
    assert cleaned[0]["a"] == "hello"
    assert cleaned[1]["a"] == "valid"


def test_parse_timestamp_naive_to_utc():
    # Naive timestamp in Asia/Kolkata (UTC+5:30)
    naive_str = "2026-11-23 10:00:00"
    parsed = parse_timestamp(naive_str, app_timezone="Asia/Kolkata")
    assert parsed.tzinfo == datetime.UTC
    # 10:00 IST is 04:30 UTC
    assert parsed.hour == 4
    assert parsed.minute == 30
    assert parsed.day == 23


def test_parse_timestamp_utc_preserved():
    utc_str = "2026-11-23T04:30:00Z"
    parsed = parse_timestamp(utc_str)
    assert parsed.tzinfo == datetime.UTC
    assert parsed.hour == 4
    assert parsed.minute == 30


def test_compute_content_hash_deterministic():
    content = "Hello world of notes."
    h1 = compute_content_hash(content)
    h2 = compute_content_hash(content)
    assert h1 == h2
    assert len(h1) == 64


def test_chunk_note_content():
    note_date = datetime.date(2026, 1, 15)
    source_type = "journal"
    short_text = "A brief reflection on testing."
    chunks = chunk_note_content(short_text, note_date, source_type)
    assert len(chunks) == 1
    assert chunks[0][0] == 0
    assert chunks[0][1] == "[2026-01-15 | journal] A brief reflection on testing."


def test_chunk_note_content_large_text_overlap():
    note_date = datetime.date(2026, 1, 20)
    source_type = "reading_note"
    sentence = (
        "This is a detailed analysis of distributed database consensus and transaction logs. "
    )
    large_text = sentence * 15  # ~1200 chars > 500
    chunks = chunk_note_content(
        large_text, note_date, source_type, chunk_size=500, chunk_overlap=80
    )
    assert len(chunks) >= 2

    for idx, header_text, raw_text in chunks:
        assert header_text.startswith(f"[{note_date} | {source_type}] ")
        assert header_text == f"[{note_date} | {source_type}] {raw_text}"

    # Verify 80-char overlap between consecutive chunks
    overlap_expected = chunks[0][2][-80:]
    assert chunks[1][2].startswith(overlap_expected)

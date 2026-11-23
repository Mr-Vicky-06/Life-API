"""Sentence-aware chunking for notes."""
from __future__ import annotations

import datetime
import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def chunk_note_content(
    content: str,
    note_date: datetime.date,
    source_type: str,
    chunk_size: int = 500,
    chunk_overlap: int = 80,
) -> list[tuple[int, str, str]]:
    """Split content into chunks of up to ~500 chars with 80 char overlap.

    Returns a list of tuples: (chunk_idx, content_with_header, raw_chunk_text).
    Header format: `[{note_date} | {source_type}] {chunk_text}`.
    """
    cleaned = content.strip()
    if not cleaned:
        return []

    if len(cleaned) <= chunk_size:
        header_text = f"[{note_date} | {source_type}] {cleaned}"
        return [(0, header_text, cleaned)]

    # Split into sentences
    sentences = _SENTENCE_SPLIT_RE.split(cleaned)
    chunks_text: list[str] = []
    current_chunk = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        # If a single sentence exceeds chunk_size, split by words
        if len(sentence) > chunk_size:
            words = sentence.split(" ")
            for word in words:
                if not current_chunk:
                    current_chunk = word
                elif len(current_chunk) + len(word) + 1 <= chunk_size:
                    current_chunk += " " + word
                else:
                    chunks_text.append(current_chunk)
                    # Carry over overlap
                    overlap_text = (
                        current_chunk[-chunk_overlap:]
                        if len(current_chunk) > chunk_overlap
                        else current_chunk
                    )
                    current_chunk = overlap_text + " " + word
            continue

        if not current_chunk:
            current_chunk = sentence
        elif len(current_chunk) + len(sentence) + 1 <= chunk_size:
            current_chunk += " " + sentence
        else:
            chunks_text.append(current_chunk)
            overlap_text = (
                current_chunk[-chunk_overlap:]
                if len(current_chunk) > chunk_overlap
                else current_chunk
            )
            current_chunk = overlap_text + " " + sentence

    if current_chunk:
        chunks_text.append(current_chunk)

    results: list[tuple[int, str, str]] = []
    for idx, c_text in enumerate(chunks_text):
        c_text = c_text.strip()
        header_text = f"[{note_date} | {source_type}] {c_text}"
        results.append((idx, header_text, c_text))

    return results

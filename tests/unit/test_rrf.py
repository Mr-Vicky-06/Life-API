"""Unit tests for Reciprocal Rank Fusion (RRF) math and deduplication."""
from __future__ import annotations

import datetime

from app.rag.hybrid import compute_rrf


def _make_hit(chunk_id: int, note_id: int, text: str = "sample text") -> dict:
    return {
        "chunk_id": chunk_id,
        "note_id": note_id,
        "note_date": datetime.date(2026, 1, 1),
        "source_type": "journal",
        "content": text,
        "snippet": text,
    }


def test_rrf_math_formula():
    # Single doc at rank 1 in vector leg: score = 1 / (60 + 1) = 1/61 ≈ 0.016393
    v_hits = [_make_hit(1, 101)]
    fused = compute_rrf(v_hits, [], k=60)
    assert len(fused) == 1
    expected_score = round(1.0 / 61.0, 6)
    assert fused[0]["score"] == expected_score


def test_rrf_overlapping_ranks_higher_than_single_leg():
    # Doc 101 appears in both legs at rank 1: score = 1/61 + 1/61 ≈ 0.032787
    # Doc 102 appears only in vector leg at rank 1: score = 1/61 ≈ 0.016393
    v_hits = [_make_hit(1, 101), _make_hit(2, 102)]
    t_hits = [_make_hit(1, 101)]

    fused = compute_rrf(v_hits, t_hits, k=60)
    assert len(fused) == 2
    assert fused[0]["note_id"] == 101
    assert fused[1]["note_id"] == 102
    assert fused[0]["score"] > fused[1]["score"]
    assert fused[0]["score"] == round(2.0 / 61.0, 6)
    assert fused[1]["score"] == round(1.0 / 62.0, 6)


def test_rrf_one_leg_empty():
    # Only term hits
    t_hits = [_make_hit(1, 101), _make_hit(2, 102)]
    fused_term_only = compute_rrf([], t_hits, k=60)
    assert len(fused_term_only) == 2
    assert fused_term_only[0]["note_id"] == 101
    assert fused_term_only[0]["score"] == round(1.0 / 61.0, 6)
    assert fused_term_only[1]["note_id"] == 102
    assert fused_term_only[1]["score"] == round(1.0 / 62.0, 6)

    # Both empty
    assert compute_rrf([], [], k=60) == []


def test_rrf_deduplication_by_note_id():
    # Two chunks belonging to the same note_id 200
    v_hits = [_make_hit(chunk_id=1, note_id=200, text="chunk 1")]
    t_hits = [_make_hit(chunk_id=2, note_id=200, text="chunk 2")]

    fused = compute_rrf(v_hits, t_hits, k=60)
    # Must deduplicate down to a single hit for note_id 200
    assert len(fused) == 1
    assert fused[0]["note_id"] == 200
    # Combined score
    assert fused[0]["score"] == round(2.0 / 61.0, 6)


def test_rrf_top_k_limiting():
    v_hits = [_make_hit(i, 100 + i) for i in range(1, 20)]
    fused = compute_rrf(v_hits, [], k=60, top_k=5)
    assert len(fused) == 5

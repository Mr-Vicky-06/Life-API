"""Hybrid search combining vector similarity and full-text search with RRF."""
from __future__ import annotations

import datetime
import re
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import rw_engine
from app.rag.embeddings import embed_texts
from app.schemas.search import SearchHit

_HEADER_STRIP_RE = re.compile(r"^\[\d{4}-\d{2}-\d{2}\s*\|\s*[^\]]+\]\s*")


def clean_snippet(content: str, max_length: int = 300) -> str:
    """Strip metadata header if present and truncate to max_length chars."""
    if not content:
        return ""
    stripped = _HEADER_STRIP_RE.sub("", content).strip()
    if len(stripped) <= max_length:
        return stripped
    return stripped[:max_length].rsplit(" ", 1)[0] + "..."


def compute_rrf(
    vector_hits: list[dict[str, Any]],
    term_hits: list[dict[str, Any]],
    k: int = 60,
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Fuse vector and term rankings using Reciprocal Rank Fusion (RRF).

    Score formula: score(d) = sum(1 / (k + rank_leg(d))).
    Deduplicates by note_id, retaining the highest scoring chunk per note.
    """
    scores_by_note: dict[int, float] = {}
    items_by_note: dict[int, dict[str, Any]] = {}

    # Rank 1-indexed for vector leg
    for rank_idx, hit in enumerate(vector_hits, start=1):
        note_id = hit["note_id"]
        rrf_contrib = 1.0 / (k + rank_idx)
        scores_by_note[note_id] = scores_by_note.get(note_id, 0.0) + rrf_contrib
        if note_id not in items_by_note:
            items_by_note[note_id] = hit

    # Rank 1-indexed for term leg
    for rank_idx, hit in enumerate(term_hits, start=1):
        note_id = hit["note_id"]
        rrf_contrib = 1.0 / (k + rank_idx)
        scores_by_note[note_id] = scores_by_note.get(note_id, 0.0) + rrf_contrib
        if note_id not in items_by_note:
            items_by_note[note_id] = hit

    # Combine and sort by score descending, then note_id ascending for determinism
    fused: list[dict[str, Any]] = []
    for note_id, score in scores_by_note.items():
        base = dict(items_by_note[note_id])
        base["score"] = round(score, 6)
        fused.append(base)

    fused.sort(key=lambda x: (-x["score"], x["note_id"]))
    return fused[:top_k]


def hybrid_search(
    session: Session | None = None,
    query: str = "",
    *,
    top_k: int = 8,
    date_from: datetime.date | None = None,
    date_to: datetime.date | None = None,
    source_type: str | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
) -> list[SearchHit]:
    """Execute vector and term searches, fusing results with RRF k=60.

    Uses bound parameters exclusively for SQL safety.
    """
    if not query or not query.strip():
        return []

    # 1. Embed query
    if embed_fn is not None:
        embeddings = embed_fn([query])
    else:
        embeddings = embed_texts([query])
    q_vec_str = str(embeddings[0])

    def _execute_queries(s: Session) -> list[SearchHit]:
        # Build dynamic WHERE clauses with bound parameters
        vec_conditions = ["1=1"]
        vec_params: dict[str, Any] = {"q_vec": q_vec_str}

        term_conditions = ["c.tsv @@ plainto_tsquery('english', :q)"]
        term_params: dict[str, Any] = {"q": query}

        if date_from is not None:
            vec_conditions.append("n.note_date >= :date_from")
            vec_params["date_from"] = date_from
            term_conditions.append("n.note_date >= :date_from")
            term_params["date_from"] = date_from

        if date_to is not None:
            vec_conditions.append("n.note_date <= :date_to")
            vec_params["date_to"] = date_to
            term_conditions.append("n.note_date <= :date_to")
            term_params["date_to"] = date_to

        if source_type is not None:
            vec_conditions.append("n.source_type = :source_type")
            vec_params["source_type"] = source_type
            term_conditions.append("n.source_type = :source_type")
            term_params["source_type"] = source_type

        # Vector Leg: top 20 by cosine distance
        vec_sql = text(
            f"""
            SELECT c.id AS chunk_id, c.note_id, n.note_date, n.source_type, c.content,
                   (c.embedding <=> CAST(:q_vec AS vector)) AS distance
            FROM note_chunks c
            JOIN notes n ON c.note_id = n.id
            WHERE {' AND '.join(vec_conditions)}
            ORDER BY c.embedding <=> CAST(:q_vec AS vector) ASC
            LIMIT 20
            """
        )
        vec_rows = s.execute(vec_sql, vec_params).mappings().all()

        vector_hits = [
            {
                "chunk_id": r["chunk_id"],
                "note_id": r["note_id"],
                "note_date": r["note_date"],
                "source_type": r["source_type"],
                "content": r["content"],
                "snippet": clean_snippet(r["content"]),
            }
            for r in vec_rows
        ]

        # Term Leg: top 20 by ts_rank_cd
        term_sql = text(
            f"""
            SELECT c.id AS chunk_id, c.note_id, n.note_date, n.source_type, c.content,
                   ts_rank_cd(c.tsv, plainto_tsquery('english', :q)) AS rank
            FROM note_chunks c
            JOIN notes n ON c.note_id = n.id
            WHERE {' AND '.join(term_conditions)}
            ORDER BY rank DESC
            LIMIT 20
            """
        )
        term_rows = s.execute(term_sql, term_params).mappings().all()

        term_hits = [
            {
                "chunk_id": r["chunk_id"],
                "note_id": r["note_id"],
                "note_date": r["note_date"],
                "source_type": r["source_type"],
                "content": r["content"],
                "snippet": clean_snippet(r["content"]),
            }
            for r in term_rows
        ]

        # 3. Fuse with RRF k=60
        fused = compute_rrf(vector_hits, term_hits, k=60, top_k=top_k)

        return [
            SearchHit(
                note_id=item["note_id"],
                note_date=item["note_date"],
                source_type=item["source_type"],
                snippet=item["snippet"],
                score=item["score"],
            )
            for item in fused
        ]

    if session is not None:
        return _execute_queries(session)

    with Session(bind=rw_engine()) as rw_session:
        return _execute_queries(rw_session)

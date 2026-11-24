"""Search API routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_rw_session
from app.deps import verify_api_key
from app.rag.hybrid import hybrid_search
from app.schemas.search import SearchHit, SearchRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["search"])


@router.post(
    "/search",
    response_model=list[SearchHit],
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_key)],
)
def search_notes(
    request: SearchRequest,
    session: Session = Depends(get_rw_session),
) -> list[SearchHit]:
    """Execute hybrid search (vector + BM25 FTS fused with RRF k=60) over notes."""
    logger.info(
        "Hybrid search requested: query=%r top_k=%d source_type=%s date_from=%s date_to=%s",
        request.query,
        request.top_k,
        request.source_type,
        request.date_from,
        request.date_to,
    )

    hits = hybrid_search(
        session=session,
        query=request.query,
        top_k=request.top_k,
        date_from=request.date_from,
        date_to=request.date_to,
        source_type=request.source_type,
    )
    return hits

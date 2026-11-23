"""Embedding generation using sentence-transformers (all-MiniLM-L6-v2)."""
from __future__ import annotations

import logging
from collections.abc import Sequence

from sentence_transformers import SentenceTransformer

from app.config import get_settings

logger = logging.getLogger(__name__)

_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    """Return cached singleton SentenceTransformer embedding model."""
    global _model
    if _model is None:
        settings = get_settings()
        logger.info("Loading embedding model %s", settings.embed_model)
        _model = SentenceTransformer(settings.embed_model)
    return _model


def embed_texts(texts: Sequence[str], batch_size: int = 32) -> list[list[float]]:
    """Embed texts into normalized 384-dimensional vectors."""
    if not texts:
        return []
    model = get_embedding_model()
    embeddings = model.encode(
        list(texts),
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [e.tolist() for e in embeddings]

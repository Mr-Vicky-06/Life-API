"""Live Ollama verification test for query rewriting."""
from __future__ import annotations

import time

import pytest

from app.rag.rewrite import rewrite_query


@pytest.mark.live
def test_live_ollama_query_rewrite():
    """Verify real llama3.1:8b rewrites follow-up with anaphora into a standalone query."""
    history = [
        "How many commits did I push in October 2026?",
        "You pushed 35 commits in October 2026 across all repositories.",
    ]
    follow_up = "How about sleep?"

    t0 = time.perf_counter()
    standalone = rewrite_query(follow_up, history=history)
    elapsed = time.perf_counter() - t0

    assert len(standalone) > 0
    # Must expand the follow-up with October or sleep context
    assert "sleep" in standalone.lower()
    print(f"\n[Live Rewrite] '{follow_up}' -> '{standalone}' in {elapsed:.2f}s")

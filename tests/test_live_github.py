"""Optional live GitHub API smoke check (skipped unless GITHUB_TOKEN is configured)."""
from __future__ import annotations

import os

import httpx
import pytest


@pytest.mark.live_github
@pytest.mark.skipif(
    not os.getenv("GITHUB_TOKEN", "").strip(),
    reason="GITHUB_TOKEN not set",
)
def test_live_github_token_authenticated_user() -> None:
    """Verify GITHUB_TOKEN authenticates cleanly against GitHub API without logging secrets."""
    token = os.environ["GITHUB_TOKEN"].strip()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Life-API",
    }
    resp = httpx.get("https://api.github.com/user", headers=headers, timeout=15.0)
    assert resp.status_code == 200
    payload = resp.json()
    assert isinstance(payload.get("login"), str) and len(payload["login"]) > 0

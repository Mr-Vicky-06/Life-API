"""GitHub commit synchronization client."""
from __future__ import annotations

import datetime
import logging
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ingestion.cleaning import clean_text, parse_timestamp
from app.ingestion.loaders import upsert_github_commits
from app.schemas.ingest import IngestResult

logger = logging.getLogger(__name__)


def sync_github_commits(
    session: Session,
    days: int = 30,
    client: httpx.Client | None = None,
) -> IngestResult:
    """Pull commits from GitHub API for the configured user within the last `days` window."""
    settings = get_settings()
    username = settings.github_username
    token = settings.github_token

    if not token or not username:
        logger.warning(
            "GitHub token or username not configured; skipping commit synchronization."
        )
        return IngestResult(
            source="github",
            inserted=0,
            updated=0,
            skipped=0,
            errors=["GitHub token or username not configured; skipping sync."],
        )

    since_dt = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)
    since_iso = since_dt.isoformat()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Life-API",
    }

    http_client = client or httpx.Client(timeout=10.0)
    should_close = client is None

    commit_rows: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        # 1. Fetch user public events or repos to find active repos
        events_url = f"https://api.github.com/users/{username}/events"
        resp = http_client.get(events_url, headers=headers)
        if resp.status_code != 200:
            errors.append(f"Failed to fetch user events: HTTP {resp.status_code}")
            return IngestResult(source="github", inserted=0, updated=0, skipped=0, errors=errors)

        events = resp.json()
        repos_seen = set()
        if isinstance(events, list):
            for ev in events:
                if isinstance(ev, dict) and ev.get("type") == "PushEvent":
                    repo_info = ev.get("repo", {})
                    repo_name = repo_info.get("name")
                    if repo_name:
                        repos_seen.add(repo_name)

        # 2. For each identified repository, fetch commits authored by user
        for repo_name in repos_seen:
            commits_url = f"https://api.github.com/repos/{repo_name}/commits"
            page = 1
            while True:
                params = {"author": username, "since": since_iso, "per_page": 100, "page": page}
                c_resp = http_client.get(commits_url, headers=headers, params=params)
                if c_resp.status_code != 200:
                    err = f"Failed to fetch commits for {repo_name}: HTTP {c_resp.status_code}"
                    errors.append(err)
                    break
                commits_data = c_resp.json()
                if not isinstance(commits_data, list) or len(commits_data) == 0:
                    break

                for c_item in commits_data:
                    sha = c_item.get("sha")
                    commit_meta = c_item.get("commit", {})
                    author_meta = commit_meta.get("author", {})
                    date_str = author_meta.get("date")
                    if not sha or not date_str:
                        continue

                    committed_at = parse_timestamp(date_str)
                    raw_msg = commit_meta.get("message", "")
                    cleaned_msg = clean_text(raw_msg)

                    stats = c_item.get("stats", {})
                    additions = stats.get("additions", 0)
                    deletions = stats.get("deletions", 0)

                    commit_rows.append({
                        "sha": sha,
                        "repo": repo_name,
                        "committed_at": committed_at,
                        "commit_date": committed_at.date(),
                        "message": cleaned_msg,
                        "additions": additions,
                        "deletions": deletions,
                    })

                page += 1
                if page > 10:  # safety bound
                    break

        result = upsert_github_commits(session, commit_rows)
        result.errors.extend(errors)
        return result
    finally:
        if should_close:
            http_client.close()

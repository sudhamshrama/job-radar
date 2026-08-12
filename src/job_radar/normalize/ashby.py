"""Ashby job boards.

    GET https://api.ashbyhq.com/posting-api/job-board/<org>

    {"jobs": [{"id": "...", "title": "...", "location": "Remote U.S.",
               "publishedAt": "2026-04-21T12:35:37.500+00:00",
               "jobUrl": "...", "isListed": true, "isRemote": true}]}

Ashby is the ATS a lot of newer companies moved to, so it reaches employers
Greenhouse misses entirely. `isListed` must be honoured — an unlisted posting
is one the company has deliberately taken off its public board.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from job_radar.fetch import fetch_json
from job_radar.models import Job, match_keywords

log = logging.getLogger("job_radar.normalize.ashby")

URL_TEMPLATE = "https://api.ashbyhq.com/posting-api/job-board/{org}"


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return datetime.now(UTC)


def normalize(org: str, payload: dict[str, Any], keywords: list[str]) -> list[Job]:
    jobs: list[Job] = []

    for entry in payload.get("jobs", []):
        # Respect the board's own visibility flag.
        if entry.get("isListed") is False:
            continue

        title = (entry.get("title") or "").strip()
        if not title:
            continue

        matched = match_keywords(title, keywords)
        if not matched:
            continue

        jobs.append(
            Job(
                source=f"ashby:{org}",
                external_id=str(entry.get("id")),
                title=title,
                company=org,
                url=entry.get("jobUrl") or entry.get("applyUrl") or "",
                location=(entry.get("location") or "").strip(),
                posted_at=_parse_time(entry.get("publishedAt")),
                matched_keywords=matched,
                raw_excerpt=title,
            )
        )

    return jobs


def collect(org: str, keywords: list[str]) -> list[Job]:
    return normalize(org, fetch_json(URL_TEMPLATE.format(org=org)), keywords)

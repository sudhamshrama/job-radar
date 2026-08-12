"""Greenhouse public job boards.

The best-behaved of the three sources: an object with a `jobs` array of clean,
structured fields.

    GET https://boards-api.greenhouse.io/v1/boards/<board>/jobs

    {"jobs": [{"id": 123, "title": "...", "absolute_url": "...",
               "updated_at": "2026-08-01T12:00:00-04:00",
               "location": {"name": "Remote"}}]}
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from job_radar.fetch import fetch_json
from job_radar.models import Job, match_keywords

log = logging.getLogger("job_radar.normalize.greenhouse")

URL_TEMPLATE = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        # Greenhouse sends offsets like "-04:00", which fromisoformat handles.
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        log.warning("unparseable timestamp", extra={"value": value})
        return datetime.now(UTC)


def normalize(board: str, payload: dict[str, Any], keywords: list[str]) -> list[Job]:
    jobs: list[Job] = []

    for entry in payload.get("jobs", []):
        title = (entry.get("title") or "").strip()
        if not title:
            continue

        matched = match_keywords(title, keywords)
        if not matched:
            continue

        location = ((entry.get("location") or {}).get("name") or "").strip()

        jobs.append(
            Job(
                source=f"greenhouse:{board}",
                external_id=str(entry.get("id")),
                title=title,
                company=board,
                url=entry.get("absolute_url", ""),
                location=location,
                posted_at=_parse_time(entry.get("updated_at")),
                matched_keywords=matched,
                raw_excerpt=title,
            )
        )

    return jobs


def collect(board: str, keywords: list[str]) -> list[Job]:
    payload = fetch_json(URL_TEMPLATE.format(board=board))
    return normalize(board, payload, keywords)

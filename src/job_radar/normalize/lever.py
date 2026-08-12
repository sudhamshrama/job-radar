"""Lever job boards.

    GET https://api.lever.co/v0/postings/<org>?mode=json

Returns a bare array. Two quirks worth naming:

*   The title field is `text`, not `title`.
*   `createdAt` is **epoch milliseconds**, not an ISO string like every other
    source here. Treating it as seconds puts every posting in 1970, which then
    lands in a TTL bucket that expires immediately — the row would vanish
    without ever erroring.

Lever was rejected in ADR 0004 after 6 of 7 probed companies returned 404. It
is included now because a wider probe found live boards (spotify, palantir,
veeva, binance, tala). The original finding stands: org tokens are not
derivable from company names and must be verified individually.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from job_radar.fetch import fetch_json
from job_radar.models import Job, match_keywords

log = logging.getLogger("job_radar.normalize.lever")

URL_TEMPLATE = "https://api.lever.co/v0/postings/{org}?mode=json"


def _parse_time(value: Any) -> datetime:
    """Lever sends epoch MILLISECONDS."""
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now(UTC)


def normalize(org: str, payload: list[Any], keywords: list[str]) -> list[Job]:
    jobs: list[Job] = []

    for entry in payload:
        if not isinstance(entry, dict):
            continue

        title = (entry.get("text") or "").strip()
        if not title:
            continue

        matched = match_keywords(title, keywords)
        if not matched:
            continue

        categories = entry.get("categories") or {}
        location = str(categories.get("location") or "").strip()
        # `country` is an ISO code ("GB", "US") and is a stronger signal than
        # the free-text location, so append it for the US filter to read.
        country = str(entry.get("country") or "").strip()
        if country and country not in location:
            location = f"{location}, {country}".strip(", ")

        jobs.append(
            Job(
                source=f"lever:{org}",
                external_id=str(entry.get("id")),
                title=title,
                company=org,
                url=entry.get("hostedUrl") or entry.get("applyUrl") or "",
                location=location,
                posted_at=_parse_time(entry.get("createdAt")),
                matched_keywords=matched,
                raw_excerpt=title,
            )
        )

    return jobs


def collect(org: str, keywords: list[str]) -> list[Job]:
    return normalize(org, fetch_json(URL_TEMPLATE.format(org=org)), keywords)

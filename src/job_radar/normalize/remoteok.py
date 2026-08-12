"""Remote OK.

    GET https://remoteok.com/api        (a User-Agent header is required)

Two things about this source that are easy to get wrong.

1. THE FIRST ELEMENT IS NOT A JOB.
   The response is a bare array whose element 0 is a legal notice:

       {"last_updated": 1786559515, "legal": "API Terms of Service: ..."}

   Iterating naively produces a record with no title, no company and no URL,
   which then sits in the database looking like a parsing bug somewhere else
   entirely. Regression test: tests/test_remoteok.py.

   Rather than skipping index 0 by position, entries lacking the required
   fields are skipped. That stays correct if Remote OK ever moves or removes
   the notice.

2. THEIR TERMS REQUIRE ATTRIBUTION.
   The notice asks consumers to link back to the Remote OK URL and name Remote
   OK as the source, on pain of suspended API access. So `url` is always the
   remoteok.com posting URL (never a bare apply link), and the dashboard must
   credit the source. This is a condition of use, not a nicety.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from job_radar.fetch import fetch_json
from job_radar.models import Job, match_keywords

log = logging.getLogger("job_radar.normalize.remoteok")

URL = "https://remoteok.com/api"
ATTRIBUTION = "Remote OK (https://remoteok.com)"

REQUIRED_FIELDS = ("id", "position")


def _parse_time(value: str | None) -> datetime:
    if not value:
        return datetime.now(UTC)
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        log.warning("unparseable timestamp", extra={"value": value})
        return datetime.now(UTC)


def normalize(payload: list[Any], keywords: list[str]) -> list[Job]:
    jobs: list[Job] = []
    skipped_notice = 0

    for entry in payload:
        if not isinstance(entry, dict):
            continue

        # The legal-notice element, and anything else malformed.
        if not all(entry.get(f) for f in REQUIRED_FIELDS):
            if "legal" in entry:
                skipped_notice += 1
            continue

        title = str(entry.get("position", "")).strip()
        tags = entry.get("tags") or []
        haystack = " ".join([title, *(str(t) for t in tags)])

        matched = match_keywords(haystack, keywords)
        if not matched:
            continue

        jobs.append(
            Job(
                source="remoteok",
                external_id=str(entry["id"]),
                title=title,
                company=str(entry.get("company", "")).strip(),
                # Attribution requirement: always the Remote OK posting URL.
                url=entry.get("url", ""),
                location=str(entry.get("location", "")).strip(),
                posted_at=_parse_time(entry.get("date")),
                matched_keywords=matched,
                raw_excerpt=title,
            )
        )

    if skipped_notice:
        log.info("skipped remoteok legal notice", extra={"count": skipped_notice})

    return jobs


def collect(keywords: list[str]) -> list[Job]:
    return normalize(fetch_json(URL), keywords)

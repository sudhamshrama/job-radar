"""Job aggregators: Remotive, Arbeitnow, Jobicy, Himalayas.

Four APIs, four different field names for the same four concepts. Rather than
four near-identical modules, each is a small spec and one loop reads them.

| source    | title    | company      | url             | date                 |
|-----------|----------|--------------|-----------------|----------------------|
| remotive  | title    | company_name | url             | publication_date ISO |
| arbeitnow | title    | company_name | url             | created_at epoch s   |
| jobicy    | jobTitle | companyName  | url             | pubDate ISO          |
| himalayas | title    | companyName  | applicationLink | pubDate epoch s      |

Location fields differ too: `candidate_required_location`, `location`, `jobGeo`,
and `locationRestrictions` — the last being a LIST rather than a string.

Remotive is the most valuable of the four because it has a real `devops`
category, so filtering happens server-side instead of over every posting.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from job_radar.fetch import fetch_json
from job_radar.models import Job, match_keywords

log = logging.getLogger("job_radar.normalize.aggregators")

SPECS: dict[str, dict[str, Any]] = {
    "remotive": {
        "url": "https://remotive.com/api/remote-jobs?category=devops&limit=200",
        "root": "jobs",
        "title": "title", "company": "company_name", "link": "url",
        "location": "candidate_required_location", "date": "publication_date",
        "date_kind": "iso",
    },
    "arbeitnow": {
        "url": "https://www.arbeitnow.com/api/job-board-api",
        "root": "data",
        "title": "title", "company": "company_name", "link": "url",
        "location": "location", "date": "created_at", "date_kind": "epoch_s",
        "extra": "tags",
    },
    "jobicy": {
        "url": "https://jobicy.com/api/v2/remote-jobs?count=100&industry=dev",
        "root": "jobs",
        "title": "jobTitle", "company": "companyName", "link": "url",
        "location": "jobGeo", "date": "pubDate", "date_kind": "iso",
    },
    "himalayas": {
        "url": "https://himalayas.app/jobs/api?limit=100",
        "root": "jobs",
        "title": "title", "company": "companyName", "link": "applicationLink",
        "location": "locationRestrictions", "date": "pubDate",
        "date_kind": "epoch_s", "extra": "categories",
    },
}


def _parse_date(value: Any, kind: str) -> datetime:
    if value in (None, ""):
        return datetime.now(UTC)
    try:
        if kind == "epoch_s":
            return datetime.fromtimestamp(int(value), tz=UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(UTC)
    except (TypeError, ValueError, OSError, OverflowError):
        return datetime.now(UTC)


def _as_text(value: Any) -> str:
    """Location is a plain string on three sources and a LIST on Himalayas."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    return str(value or "").strip()


def normalize(source_id: str, payload: Any, keywords: list[str]) -> list[Job]:
    spec = SPECS[source_id]

    rows = payload.get(spec["root"], []) if isinstance(payload, dict) else payload
    jobs: list[Job] = []

    for entry in rows or []:
        if not isinstance(entry, dict):
            continue

        title = str(entry.get(spec["title"]) or "").strip()
        if not title:
            continue

        extra = _as_text(entry.get(spec.get("extra", ""), ""))
        matched = match_keywords(f"{title} {extra}", keywords)
        if not matched:
            continue

        jobs.append(
            Job(
                source=source_id,
                external_id=str(entry.get("id") or entry.get("slug") or title),
                title=title,
                company=str(entry.get(spec["company"]) or "").strip(),
                url=str(entry.get(spec["link"]) or ""),
                location=_as_text(entry.get(spec["location"])),
                posted_at=_parse_date(entry.get(spec["date"]), spec["date_kind"]),
                matched_keywords=matched,
                raw_excerpt=title,
            )
        )

    return jobs


def collect(source_id: str, keywords: list[str]) -> list[Job]:
    return normalize(source_id, fetch_json(SPECS[source_id]["url"]), keywords)

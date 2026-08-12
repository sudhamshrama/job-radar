"""Query Lambda — the read side, behind API Gateway.

    GET /jobs?days=7&source=greenhouse&q=kubernetes&limit=100

Access pattern
--------------
"Recent postings, newest first" is the only pattern the dashboard needs, and
the table was designed for it: GSI1 is partitioned by day (`POSTED#2026-08-12`)
with an ISO timestamp sort key.

So a request for the last 7 days is 7 Query calls — one per date bucket —
merged and sorted. Not a Scan.

Why that distinction matters: a Scan reads every item in the table and is
billed for all of them, so its cost grows with total table size regardless of
how few rows come back. These Queries read only the partitions asked for. At
200 items the difference is invisible; the point is that it stays correct at
200,000, and choosing Scan now would mean rewriting later.

The date-bucketed partition key is what makes this possible. A constant key
like "ALL" would be a single hot partition; no bucket at all would force a Scan.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
from boto3.dynamodb.conditions import Key

from job_radar import logging_setup

log = logging_setup.configure()

MAX_DAYS = 30
MAX_LIMIT = 500
DEFAULT_DAYS = 7
DEFAULT_LIMIT = 100


def _table():
    return boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _int_param(params: dict[str, Any], name: str, default: int, cap: int) -> int:
    """Parse and clamp a query-string integer.

    Clamping rather than erroring: `?days=99999` is far more likely to be a
    careless client than an attack, and an unbounded value would fan out into
    99,999 Query calls. The cap is the actual protection.
    """
    raw = params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(value, cap))


def _fetch(days: int) -> list[dict[str, Any]]:
    table = _table()
    today = datetime.now(UTC).date()
    items: list[dict[str, Any]] = []

    for offset in range(days):
        bucket = f"POSTED#{(today - timedelta(days=offset)).isoformat()}"
        response = table.query(
            IndexName="gsi1",
            KeyConditionExpression=Key("gsi1pk").eq(bucket),
            ScanIndexForward=False,  # newest first within the day
        )
        items.extend(response.get("Items", []))

    return items


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    params = (event or {}).get("queryStringParameters") or {}

    days = _int_param(params, "days", DEFAULT_DAYS, MAX_DAYS)
    limit = _int_param(params, "limit", DEFAULT_LIMIT, MAX_LIMIT)
    source = (params.get("source") or "").strip().lower()
    search = (params.get("q") or "").strip().lower()

    items = _fetch(days)

    if source:
        items = [i for i in items if str(i.get("source", "")).lower().startswith(source)]

    if search:
        items = [
            i for i in items
            if search in str(i.get("title", "")).lower()
            or search in str(i.get("company", "")).lower()
        ]

    items.sort(key=lambda i: str(i.get("posted_at", "")), reverse=True)
    total = len(items)
    items = items[:limit]

    log.info("query", extra={"days": days, "source": source, "q": search,
                             "matched": total, "returned": len(items)})

    body = {
        "count": len(items),
        "total_matched": total,
        "days": days,
        # Remote OK's API terms require naming them as a source wherever their
        # postings are shown. See ADR 0004 and the note in normalize/remoteok.py.
        "attribution": {
            "remoteok": "Job data from Remote OK — https://remoteok.com",
        },
        "jobs": [
            {
                "id": i.get("job_id"),
                "title": i.get("title"),
                "company": i.get("company"),
                "url": i.get("url"),
                "location": i.get("location"),
                "source": i.get("source"),
                "posted_at": i.get("posted_at"),
                "keywords": i.get("matched_keywords", []),
            }
            for i in items
        ],
    }

    return {
        "statusCode": 200,
        "headers": {
            "content-type": "application/json",
            # Postings change at most every 6 hours, so a short browser cache
            # costs nothing and removes repeat Lambda invocations.
            "cache-control": "public, max-age=300",
        },
        "body": json.dumps(body, default=str),
    }

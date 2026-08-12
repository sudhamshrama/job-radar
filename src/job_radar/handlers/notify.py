"""Notify Lambda — DynamoDB Streams consumer, emails a digest of new roles.

Why only INSERT events matter
-----------------------------
Ingest runs every 6 hours and rewrites every posting it finds, because the
write is idempotent by design (same posting -> same key -> overwrite). That
means each run produces ~200 MODIFY stream records and only a handful of
INSERTs. `ingested_at` changes every run, so the items really are modified —
there is no way to make the rewrite a no-op.

Only INSERTs are new jobs. The rest is the pipeline re-confirming what it
already knew, and emailing about it would make the notification worthless
within a day.

That filter is applied on the **event source mapping**, not here. Filtering in
code still pays for the invocation; filtering at the source means Lambda is
never invoked for a MODIFY at all. With ~200 MODIFYs per run, six runs a day,
that is roughly 1,200 invocations a day avoided.

Ordering and poison records
---------------------------
Stream shards are processed in order, and a record that always raises will be
retried until it expires — blocking every record behind it. That is why this
consumer has a real dead-letter queue and bounded retries: one malformed item
must not stop notifications indefinitely.
"""

from __future__ import annotations

import os
from typing import Any

import boto3

from job_radar import logging_setup

log = logging_setup.configure()

MAX_LISTED = 25


def _sns():
    return boto3.client("sns")


def _plain(image: dict[str, Any], key: str, default: str = "") -> str:
    """Pull a value out of the DynamoDB stream's typed representation.

    Stream records use the low-level wire format ({"S": "..."}), not the
    friendly shapes the resource API returns.
    """
    cell = image.get(key) or {}
    if "S" in cell:
        return str(cell["S"])
    if "N" in cell:
        return str(cell["N"])
    if "L" in cell:
        return ", ".join(_plain({"v": v}, "v") for v in cell["L"])
    return default


def _format(jobs: list[dict[str, str]]) -> tuple[str, str]:
    shown = jobs[:MAX_LISTED]
    lines = []

    for job in shown:
        lines.append(f"{job['title']}")
        meta = " · ".join(p for p in (job["company"], job["location"]) if p)
        if meta:
            lines.append(f"  {meta}")
        if job["keywords"]:
            lines.append(f"  matched: {job['keywords']}")
        lines.append(f"  {job['url']}")
        lines.append("")

    if len(jobs) > MAX_LISTED:
        lines.append(f"...and {len(jobs) - MAX_LISTED} more.")
        lines.append("")

    lines.append("Dashboard: " + os.environ.get("DASHBOARD_URL", "(not set)"))
    lines.append("Job data from Remote OK — https://remoteok.com")

    count = len(jobs)
    subject = f"job-radar: {count} new DevOps role{'' if count == 1 else 's'}"
    return subject[:100], "\n".join(lines)


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    records = (event or {}).get("Records", [])
    jobs: list[dict[str, str]] = []

    for record in records:
        # Belt and braces: the event source mapping already filters to INSERT,
        # but a mapping can be edited in the console without touching code.
        if record.get("eventName") != "INSERT":
            continue

        image = (record.get("dynamodb") or {}).get("NewImage") or {}
        title = _plain(image, "title")
        if not title:
            continue

        jobs.append({
            "title": title,
            "company": _plain(image, "company"),
            "location": _plain(image, "location"),
            "url": _plain(image, "url"),
            "keywords": _plain(image, "matched_keywords"),
        })

    if not jobs:
        log.info("no new jobs in batch", extra={"records": len(records)})
        return {"records": len(records), "new_jobs": 0, "published": False}

    subject, body = _format(jobs)
    _sns().publish(
        TopicArn=os.environ["TOPIC_ARN"],
        Subject=subject,
        Message=body,
    )

    log.info("published digest", extra={"records": len(records), "new_jobs": len(jobs)})
    return {"records": len(records), "new_jobs": len(jobs), "published": True}

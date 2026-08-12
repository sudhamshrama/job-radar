"""The one record shape every source normalizes into.

Three sources return three genuinely different structures (see ADR 0004). This
module defines the single schema they all collapse to, and the DynamoDB key
design that schema implies.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# How long a posting stays in the table before DynamoDB deletes it for free.
TTL_DAYS = 90


def _now() -> datetime:
    return datetime.now(UTC)


def stable_job_id(source: str, external_id: str) -> str:
    """Deterministic ID for a posting.

    Idempotency depends on this: the same posting seen on two runs must produce
    the same ID, so the second write overwrites the first instead of creating a
    duplicate. A random UUID here would mean every scheduled run duplicated the
    entire dataset.
    """
    digest = hashlib.sha256(f"{source}:{external_id}".encode()).hexdigest()
    return digest[:16]


@dataclass
class Job:
    """A normalized job posting."""

    source: str          # "greenhouse:datadog", "remoteok", "hackernews"
    external_id: str     # the source's own ID
    title: str
    company: str
    url: str
    location: str = ""
    posted_at: datetime = field(default_factory=_now)
    matched_keywords: list[str] = field(default_factory=list)
    raw_excerpt: str = ""   # short snippet, useful when parsing goes wrong

    @property
    def job_id(self) -> str:
        return stable_job_id(self.source, self.external_id)

    def to_item(self) -> dict[str, Any]:
        """Render as a DynamoDB item.

        Key design
        ----------
        pk = JOB#<job_id>          partition key, one item per posting
        sk = META                  fixed; room for related items later

        GSI1 answers "show me recent postings", which the read API needs:
        gsi1pk = POSTED#<YYYY-MM-DD>
        gsi1sk = <iso timestamp>#<job_id>

        The date bucket in gsi1pk matters. A constant value like "ALL" would put
        every write into one partition and create a hot partition. Bucketing by
        day spreads writes and makes "last 7 days" a query over 7 partitions,
        which is the standard time-series pattern for DynamoDB.
        """
        posted = self.posted_at.astimezone(UTC)
        expires = int((posted + timedelta(days=TTL_DAYS)).timestamp())

        return {
            "pk": f"JOB#{self.job_id}",
            "sk": "META",
            "gsi1pk": f"POSTED#{posted.date().isoformat()}",
            "gsi1sk": f"{posted.isoformat()}#{self.job_id}",
            "job_id": self.job_id,
            "source": self.source,
            "external_id": str(self.external_id),
            "title": self.title,
            "company": self.company,
            "url": self.url,
            "location": self.location,
            "posted_at": posted.isoformat(),
            "ingested_at": _now().isoformat(),
            "matched_keywords": self.matched_keywords,
            "raw_excerpt": self.raw_excerpt[:500],
            # DynamoDB deletes expired items at no cost, which keeps the table
            # inside the 25 GB always-free allowance without a cleanup job.
            "ttl": expires,
        }


def match_keywords(text: str, keywords: list[str]) -> list[str]:
    """Return which keywords appear in text.

    Word-boundary matched so "sre" does not match "closure" and "kubernetes"
    does not match a substring of some unrelated word.
    """
    found = []
    for kw in keywords:
        if re.search(rf"\b{re.escape(kw)}\b", text, re.IGNORECASE):
            found.append(kw)
    return found

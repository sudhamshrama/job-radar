"""Ingest Lambda — fetch every source, normalize, write to DynamoDB.

Partial failure is the central design decision here.

ADR 0004 records that sources break without warning: companies switch ATS
vendors, board tokens are retired, rate limits appear. With 12 Greenhouse boards
plus two other APIs, the probability that *all* of them work on any given run is
not 1.

So one dead source must never fail the run. Each source is isolated; failures
are counted, logged, and reported. The handler raises only when **every** source
failed, which is the signal that something systemic is wrong (no network, no
credentials, config missing) rather than one board being retired.

That distinction is what makes the CloudWatch alarm meaningful: an alarm that
fires every time one of fourteen sources hiccups gets muted within a week.
"""

from __future__ import annotations

import os
from typing import Any

from job_radar import config as config_module
from job_radar import logging_setup, store
from job_radar.location import is_us
from job_radar.normalize import (
    aggregators,
    ashby,
    greenhouse,
    hackernews,
    lever,
    remoteok,
)

# Source types that fan out over a list of boards/orgs. Every board is isolated
# separately so one retired board cannot take out the rest.
#
# These hold MODULES, not bound functions. Storing `greenhouse.collect` here
# would resolve the function once at import time, which makes it unpatchable in
# tests and — worse — means editing the module no longer changes what runs.
MULTI_BOARD = {
    "greenhouse": (greenhouse, "boards"),
    "ashby": (ashby, "orgs"),
    "lever": (lever, "orgs"),
}

SINGLE = {
    "remoteok": remoteok,
    "algolia": hackernews,
}

log = logging_setup.configure()


def _collect_all(cfg: config_module.Config) -> tuple[list, list[dict[str, Any]]]:
    """Run every source. Returns (jobs, failures)."""
    jobs: list = []
    failures: list[dict[str, Any]] = []

    for source in cfg.sources:
        source_type = source.get("type")

        # Board-based ATS sources: one config entry, many boards, each isolated.
        if source_type in MULTI_BOARD:
            module, key = MULTI_BOARD[source_type]
            for board in source.get(key, []):
                label = f"{source_type}:{board}"
                try:
                    found = module.collect(board, cfg.match_keywords)
                    jobs.extend(found)
                    log.info("source ok", extra={"source": label, "jobs": len(found)})
                except Exception as exc:
                    failures.append({"source": label, "error": str(exc)})
                    log.warning("source failed",
                                extra={"source": label, "error": str(exc)})
            continue

        name = source.get("id", source_type)

        if source_type == "aggregator":
            def handler(kw, _name=name):
                return aggregators.collect(_name, kw)
        else:
            module = SINGLE.get(source_type)
            if module is None:
                log.warning("unknown source type", extra={"type": source_type})
                continue

            def handler(kw, _module=module):
                return _module.collect(kw)

        try:
            found = handler(cfg.match_keywords)
            jobs.extend(found)
            log.info("source ok", extra={"source": name, "jobs": len(found)})
        except Exception as exc:
            failures.append({"source": name, "error": str(exc)})
            log.warning("source failed", extra={"source": name, "error": str(exc)})

    return jobs, failures


def _deduplicate(jobs: list) -> list:
    """Collapse jobs sharing a job_id.

    The same posting can legitimately appear twice in one run — a company
    cross-posts to Remote OK and its own Greenhouse board. Those have different
    sources so different IDs, which is intended. This only removes exact
    duplicates within a run, which would otherwise mean two writes for one item.
    """
    seen: dict[str, Any] = {}
    for job in jobs:
        seen.setdefault(job.job_id, job)
    return list(seen.values())


def handler(event: dict[str, Any] | None = None, context: Any = None) -> dict[str, Any]:
    cfg = config_module.load()

    jobs, failures = _collect_all(cfg)

    # US-only filter, applied centrally rather than in each normalizer: it is
    # one policy, and duplicating it across eight sources would guarantee the
    # sources drift apart. `raw_excerpt` is passed because Hacker News postings
    # have no location field — "REMOTE (US)" only appears in the prose.
    before = len(jobs)
    if cfg.us_only:
        jobs = [j for j in jobs if is_us(j.location, j.raw_excerpt)]
        log.info("us filter applied",
                 extra={"before": before, "after": len(jobs),
                        "dropped": before - len(jobs)})

    unique = _deduplicate(jobs)

    total_sources = sum(
        len(s.get("boards", s.get("orgs", []))) if s.get("type") in MULTI_BOARD else 1
        for s in cfg.sources
    )

    written = 0
    if unique:
        written = store.put_jobs(unique)

    result = {
        "sources_total": total_sources,
        "sources_failed": len(failures),
        "jobs_before_us_filter": before,
        "jobs_found": len(jobs),
        "jobs_unique": len(unique),
        "jobs_written": written,
        "failures": failures,
    }

    log.info("ingest complete", extra=result)

    # Every source failed: systemic, not a retired board. Raising marks the
    # invocation as an error so the Lambda error alarm fires and EventBridge
    # records a failed invocation.
    if failures and len(failures) == total_sources:
        raise RuntimeError(f"all {total_sources} sources failed: {failures}")

    return result


# Allow `python -m job_radar.handlers.ingest` for a local smoke test.
if __name__ == "__main__":  # pragma: no cover
    import json

    os.environ.setdefault("TABLE_NAME", "job-radar-dev-jobs")
    print(json.dumps(handler({}, None), indent=2, default=str))

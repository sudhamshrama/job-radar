"""DynamoDB writes.

boto3 ships with the Lambda runtime, so this adds nothing to the deployment
package.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

import boto3

from job_radar.models import Job

log = logging.getLogger("job_radar.store")


def _table():
    name = os.environ["TABLE_NAME"]
    return boto3.resource("dynamodb").Table(name)


def put_jobs(jobs: Iterable[Job]) -> int:
    """Write jobs, overwriting any existing item with the same key.

    Idempotency comes from `Job.job_id` being a stable hash of
    (source, external_id). Re-ingesting the same posting overwrites its item
    rather than creating a duplicate, so a scheduled run every few hours does
    not multiply the dataset.

    `batch_writer` handles batching into 25-item requests and retrying
    unprocessed items — the retry matters on a provisioned-capacity table,
    where a burst of writes can be throttled.
    """
    table = _table()
    written = 0

    with table.batch_writer(overwrite_by_pkeys=["pk", "sk"]) as batch:
        for job in jobs:
            batch.put_item(Item=job.to_item())
            written += 1

    log.info("wrote jobs to dynamodb", extra={"count": written})
    return written

"""Ingest handler: partial-failure behaviour and DynamoDB writes.

AWS is mocked with moto, so these run offline and cost nothing.
"""

import boto3
import pytest
from moto import mock_aws

from job_radar import config as config_module
from job_radar.handlers import ingest
from job_radar.models import Job

TABLE = "job-radar-test-jobs"


@pytest.fixture
def dynamo(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE)
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE,
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
                {"AttributeName": "sk", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)


@pytest.fixture
def cfg():
    return config_module.Config(
        match_keywords=["devops"],
        sources=[
            {"id": "greenhouse", "type": "greenhouse", "boards": ["alpha", "beta"]},
            {"id": "remoteok", "type": "remoteok"},
        ],
    )


def _job(external_id="1", source="greenhouse:alpha", location="Austin, TX"):
    # A location is required: the handler applies a US-only filter, so a job
    # with no location is legitimately dropped as "unknown is not United States".
    return Job(
        source=source,
        external_id=external_id,
        title="DevOps Engineer",
        company="alpha",
        url="https://example.com/1",
        location=location,
    )


def test_one_dead_board_does_not_fail_the_run(monkeypatch, cfg):
    """The whole point of the design.

    With 14 sources, the chance all of them work on a given run is not 1.
    A retired board must not stop the other thirteen.
    """
    def fake_greenhouse(board, keywords):
        if board == "beta":
            raise RuntimeError("404 board retired")
        return [_job("1")]

    monkeypatch.setattr(ingest.greenhouse, "collect", fake_greenhouse)
    monkeypatch.setattr(ingest.remoteok, "collect", lambda kw: [_job("2", "remoteok")])

    jobs, failures = ingest._collect_all(cfg)

    assert len(jobs) == 2
    assert len(failures) == 1
    assert failures[0]["source"] == "greenhouse:beta"


def test_all_sources_failing_raises(monkeypatch, cfg, dynamo):
    """Total failure is systemic — no network, no config — and must alarm."""
    def boom(*args, **kwargs):
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(ingest.greenhouse, "collect", boom)
    monkeypatch.setattr(ingest.remoteok, "collect", boom)
    monkeypatch.setattr(config_module, "load", lambda *a, **k: cfg)

    with pytest.raises(RuntimeError, match="all 3 sources failed"):
        ingest.handler({}, None)


def test_partial_failure_still_writes_and_reports(monkeypatch, cfg, dynamo):
    monkeypatch.setattr(config_module, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(
        ingest.greenhouse, "collect",
        lambda board, kw: [] if board == "beta" else [_job("1")],
    )
    monkeypatch.setattr(ingest.remoteok, "collect", lambda kw: [_job("2", "remoteok")])

    result = ingest.handler({}, None)

    assert result["jobs_written"] == 2
    assert result["sources_failed"] == 0
    assert dynamo.scan()["Count"] == 2


def test_reingesting_the_same_posting_does_not_duplicate(monkeypatch, cfg, dynamo):
    """Idempotency: the scheduled run must not multiply the dataset."""
    monkeypatch.setattr(config_module, "load", lambda *a, **k: cfg)
    monkeypatch.setattr(ingest.greenhouse, "collect",
                        lambda board, kw: [_job("1")] if board == "alpha" else [])
    monkeypatch.setattr(ingest.remoteok, "collect", lambda kw: [])

    ingest.handler({}, None)
    ingest.handler({}, None)
    ingest.handler({}, None)

    assert dynamo.scan()["Count"] == 1


def test_duplicates_within_one_run_are_collapsed():
    jobs = [_job("1"), _job("1"), _job("2")]

    assert len(ingest._deduplicate(jobs)) == 2


def test_cross_posted_jobs_are_kept_separate():
    """Same ID on two sources is two real postings, not a duplicate."""
    jobs = [_job("1", "greenhouse:alpha"), _job("1", "remoteok")]

    assert len(ingest._deduplicate(jobs)) == 2

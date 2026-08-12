"""Query handler: access pattern, filtering and input clamping."""

import json
from datetime import UTC, datetime, timedelta

import boto3
import pytest
from moto import mock_aws

from job_radar.handlers import query
from job_radar.models import Job

TABLE = "job-radar-test-query"


@pytest.fixture
def table(monkeypatch):
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
                {"AttributeName": "gsi1pk", "AttributeType": "S"},
                {"AttributeName": "gsi1sk", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "gsi1",
                "KeySchema": [
                    {"AttributeName": "gsi1pk", "KeyType": "HASH"},
                    {"AttributeName": "gsi1sk", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE)


def _put(table, *, days_ago=0, title="DevOps Engineer", company="acme",
         source="greenhouse:acme", external_id=None):
    posted = datetime.now(UTC) - timedelta(days=days_ago)
    job = Job(
        source=source,
        external_id=external_id or f"{title}-{days_ago}-{company}",
        title=title,
        company=company,
        url="https://example.com/1",
        posted_at=posted,
    )
    table.put_item(Item=job.to_item())
    return job


def _body(response):
    return json.loads(response["body"])


def test_returns_only_requested_day_window(table):
    _put(table, days_ago=0, external_id="a")
    _put(table, days_ago=2, external_id="b")
    _put(table, days_ago=20, external_id="c")   # outside a 7-day window

    body = _body(query.handler({"queryStringParameters": {"days": "7"}}, None))

    assert body["count"] == 2


def test_results_are_newest_first(table):
    _put(table, days_ago=3, title="Older SRE", external_id="old")
    _put(table, days_ago=0, title="Newer SRE", external_id="new")

    body = _body(query.handler({"queryStringParameters": {"days": "7"}}, None))

    assert body["jobs"][0]["title"] == "Newer SRE"


def test_filters_by_source_prefix(table):
    _put(table, source="greenhouse:datadog", external_id="g")
    _put(table, source="hackernews", external_id="h")

    body = _body(query.handler({"queryStringParameters": {"source": "hackernews"}}, None))

    assert body["count"] == 1
    assert body["jobs"][0]["source"] == "hackernews"


def test_free_text_matches_title_and_company(table):
    _put(table, title="Platform Engineer", company="grafanalabs", external_id="1")
    _put(table, title="SRE", company="mongodb", external_id="2")

    assert _body(query.handler({"queryStringParameters": {"q": "grafana"}}, None))["count"] == 1
    assert _body(query.handler({"queryStringParameters": {"q": "platform"}}, None))["count"] == 1


def test_days_parameter_is_clamped(table):
    """?days=99999 must not fan out into 99,999 Query calls."""
    body = _body(query.handler({"queryStringParameters": {"days": "99999"}}, None))

    assert body["days"] == query.MAX_DAYS


def test_garbage_parameters_fall_back_to_defaults(table):
    body = _body(query.handler({"queryStringParameters": {"days": "abc", "limit": ""}}, None))

    assert body["days"] == query.DEFAULT_DAYS


def test_missing_query_string_does_not_error(table):
    """API Gateway omits queryStringParameters entirely when there are none."""
    body = _body(query.handler({}, None))

    assert body["count"] == 0
    assert body["days"] == query.DEFAULT_DAYS


def test_limit_caps_returned_rows_but_reports_true_total(table):
    for n in range(5):
        _put(table, external_id=f"job-{n}")

    body = _body(query.handler({"queryStringParameters": {"limit": "2"}}, None))

    assert body["count"] == 2
    assert body["total_matched"] == 5


def test_response_carries_remoteok_attribution(table):
    """Their API terms require naming Remote OK wherever postings are shown."""
    body = _body(query.handler({}, None))

    assert "remoteok" in body["attribution"]
    assert "remoteok.com" in body["attribution"]["remoteok"]

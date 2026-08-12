"""Notify handler: INSERT-only semantics and stream record decoding."""

import boto3
import pytest
from moto import mock_aws

from job_radar.handlers import notify


def _record(event_name="INSERT", title="Senior DevOps Engineer", company="acme"):
    return {
        "eventName": event_name,
        "dynamodb": {
            "NewImage": {
                "title": {"S": title},
                "company": {"S": company},
                "location": {"S": "Remote"},
                "url": {"S": "https://example.com/1"},
                "matched_keywords": {"L": [{"S": "devops"}, {"S": "kubernetes"}]},
            }
        },
    }


@pytest.fixture
def topic(monkeypatch):
    with mock_aws():
        arn = boto3.client("sns", region_name="us-east-1").create_topic(
            Name="job-radar-test-alerts"
        )["TopicArn"]
        monkeypatch.setenv("TOPIC_ARN", arn)
        monkeypatch.setenv("DASHBOARD_URL", "https://example.cloudfront.net")
        yield arn


def test_modify_events_are_ignored(topic):
    """Ingest rewrites ~200 items every run; those are MODIFY, not new jobs.

    Emailing about them would make the notification worthless within a day.
    """
    event = {"Records": [_record("MODIFY"), _record("MODIFY")]}

    result = notify.handler(event, None)

    assert result["new_jobs"] == 0
    assert result["published"] is False


def test_mixed_batch_reports_only_inserts(topic):
    event = {"Records": [_record("MODIFY"), _record("INSERT"), _record("REMOVE")]}

    result = notify.handler(event, None)

    assert result["new_jobs"] == 1
    assert result["published"] is True


def test_empty_batch_does_not_publish(topic):
    assert notify.handler({"Records": []}, None)["published"] is False


def test_records_without_a_title_are_skipped(topic):
    broken = {"eventName": "INSERT", "dynamodb": {"NewImage": {"company": {"S": "x"}}}}

    assert notify.handler({"Records": [broken]}, None)["new_jobs"] == 0


def test_missing_newimage_does_not_raise(topic):
    """A malformed record must not become a poison pill blocking the shard."""
    event = {"Records": [{"eventName": "INSERT"}, {"eventName": "INSERT", "dynamodb": {}}]}

    assert notify.handler(event, None)["new_jobs"] == 0


def test_dynamodb_list_type_is_decoded(topic):
    """Stream records use the low-level wire format, not friendly shapes."""
    subject, body = notify._format([{
        "title": "SRE", "company": "acme", "location": "Remote",
        "url": "https://x", "keywords": "devops, kubernetes",
    }])

    assert "devops, kubernetes" in body
    assert subject == "job-radar: 1 new DevOps role"


def test_subject_pluralises_and_fits_sns_limit(topic):
    jobs = [{"title": f"J{n}", "company": "c", "location": "",
             "url": "https://x", "keywords": ""} for n in range(40)]

    subject, body = notify._format(jobs)

    assert subject == "job-radar: 40 new DevOps roles"
    assert len(subject) <= 100
    assert "and 15 more" in body


def test_body_carries_remoteok_attribution(topic):
    _, body = notify._format([{"title": "SRE", "company": "c", "location": "",
                               "url": "https://x", "keywords": ""}])

    assert "remoteok.com" in body

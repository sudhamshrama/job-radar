"""Record schema, keyword matching and DynamoDB key design."""

from datetime import UTC, datetime

from job_radar.models import Job, match_keywords, stable_job_id


def _job(**overrides):
    defaults = dict(
        source="greenhouse:datadog",
        external_id="12345",
        title="Senior DevOps Engineer",
        company="datadog",
        url="https://example.com/job/12345",
        location="Remote",
        posted_at=datetime(2026, 8, 12, 9, 30, tzinfo=UTC),
        matched_keywords=["devops"],
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_job_id_is_stable_across_runs():
    """Idempotency depends on this.

    A random ID would mean every scheduled run duplicated the entire dataset.
    """
    assert stable_job_id("greenhouse:datadog", "123") == stable_job_id(
        "greenhouse:datadog", "123"
    )


def test_job_id_differs_by_source():
    """The same posting cross-posted to two boards is two records, by design."""
    assert stable_job_id("greenhouse:datadog", "123") != stable_job_id("remoteok", "123")


def test_gsi_partition_is_bucketed_by_day():
    """A constant GSI partition key would create a hot partition.

    Bucketing by date spreads writes and makes "last 7 days" a query over
    7 partitions — the standard DynamoDB time-series pattern.
    """
    item = _job().to_item()

    assert item["gsi1pk"] == "POSTED#2026-08-12"
    assert item["gsi1sk"].startswith("2026-08-12T09:30:00+00:00#")


def test_sort_key_orders_chronologically_within_a_day():
    early = _job(external_id="a", posted_at=datetime(2026, 8, 12, 1, tzinfo=UTC))
    late = _job(external_id="b", posted_at=datetime(2026, 8, 12, 23, tzinfo=UTC))

    assert early.to_item()["gsi1sk"] < late.to_item()["gsi1sk"]


def test_ttl_is_ninety_days_after_posting():
    item = _job().to_item()
    posted = datetime(2026, 8, 12, 9, 30, tzinfo=UTC).timestamp()

    assert item["ttl"] == int(posted + 90 * 86400)


def test_naive_and_aware_times_normalize_to_utc():
    aware = _job(posted_at=datetime(2026, 8, 12, 9, 30, tzinfo=UTC))

    assert aware.to_item()["posted_at"].endswith("+00:00")


def test_raw_excerpt_is_truncated():
    item = _job(raw_excerpt="x" * 5000).to_item()

    assert len(item["raw_excerpt"]) == 500


def test_keyword_matching_respects_word_boundaries():
    """"sre" must not match "closure"."""
    assert match_keywords("Closure specialist", ["sre"]) == []
    assert match_keywords("Senior SRE, Platform", ["sre"]) == ["sre"]


def test_keyword_matching_is_case_insensitive():
    assert match_keywords("DEVOPS ENGINEER", ["devops"]) == ["devops"]


def test_multiword_keywords_match():
    assert match_keywords("Staff Platform Engineer", ["platform engineer"]) == [
        "platform engineer"
    ]

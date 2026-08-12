"""Remote OK normalization.

The first test is the important one: it is a regression test for a real trap in
the live API, captured from an actual response on 2026-08-12.
"""

from job_radar.normalize import remoteok

# Element 0 is the genuine legal notice returned by https://remoteok.com/api.
LEGAL_NOTICE = {
    "last_updated": 1786559515,
    "legal": (
        "API Terms of Service: Please link back (with follow, and without "
        "nofollow!) to the URL on Remote OK and mention Remote OK as a source"
    ),
}

REAL_JOB = {
    "id": "1136451",
    "slug": "remote-devops-engineer-acme-1136451",
    "company": "Acme",
    "position": "Senior DevOps Engineer",
    "date": "2026-08-11T20:29:53+00:00",
    "location": "Remote",
    "tags": ["devops", "aws"],
    "url": "https://remoteOK.com/remote-jobs/remote-devops-engineer-acme-1136451",
}

IRRELEVANT_JOB = {
    "id": "999",
    "company": "Someone",
    "position": "Ganger",
    "date": "2026-08-11T20:29:53+00:00",
    "location": "Chinchilla",
    "tags": ["hr", "legal"],
    "url": "https://remoteOK.com/remote-jobs/999",
}


def test_legal_notice_element_is_not_ingested_as_a_job(keywords):
    """The array's first element is a ToS notice, not a posting.

    Iterating naively produces an item with no title, no company and no URL,
    which then looks like a bug somewhere else entirely.
    """
    jobs = remoteok.normalize([LEGAL_NOTICE, REAL_JOB], keywords)

    assert len(jobs) == 1
    assert jobs[0].title == "Senior DevOps Engineer"
    assert all(job.title for job in jobs)
    assert all(job.url for job in jobs)


def test_notice_skipped_by_shape_not_by_position(keywords):
    """Skipping index 0 by position would break if the notice moves."""
    jobs = remoteok.normalize([REAL_JOB, LEGAL_NOTICE], keywords)

    assert len(jobs) == 1
    assert jobs[0].external_id == "1136451"


def test_non_matching_jobs_are_filtered(keywords):
    jobs = remoteok.normalize([LEGAL_NOTICE, REAL_JOB, IRRELEVANT_JOB], keywords)

    assert [j.external_id for j in jobs] == ["1136451"]


def test_matches_on_tags_not_only_title(keywords):
    entry = dict(REAL_JOB, position="Senior Engineer", tags=["kubernetes"])

    jobs = remoteok.normalize([entry], keywords)

    assert len(jobs) == 1
    assert jobs[0].matched_keywords == ["kubernetes"]


def test_url_points_back_to_remoteok(keywords):
    """Their terms require linking back to the Remote OK posting URL."""
    jobs = remoteok.normalize([REAL_JOB], keywords)

    assert "remoteok.com" in jobs[0].url.lower()


def test_malformed_entries_do_not_raise(keywords):
    payload = [LEGAL_NOTICE, {}, {"id": "1"}, {"position": "DevOps"}, "not a dict", REAL_JOB]

    jobs = remoteok.normalize(payload, keywords)

    assert len(jobs) == 1

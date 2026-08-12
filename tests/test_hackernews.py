"""Hacker News normalization.

Fixtures are shaped from real Algolia responses captured 2026-08-12.
"""

from job_radar.normalize import hackernews

# Both threads are posted seconds apart by the same author every month.
SEARCH_PAYLOAD = {
    "hits": [
        {
            "objectID": "49156682",
            "title": "Ask HN: Who wants to be hired? (August 2026)",
            "created_at": "2026-08-03T15:00:01Z",
        },
        {
            "objectID": "49156683",
            "title": "Ask HN: Who is hiring? (August 2026)",
            "created_at": "2026-08-03T15:00:00Z",
        },
    ]
}

COMMENT_HTML = (
    "Snout <a href=\"https:&#x2F;&#x2F;snout.com&#x2F;\" rel=\"nofollow\">"
    "https:&#x2F;&#x2F;snout.com&#x2F;</a> | Senior DevOps Engineer | Remote US | Full Time"
    "<p>We run Kubernetes on AWS and are looking for help with our platform."
)

ITEM_PAYLOAD = {
    "children": [
        {
            "id": 49156689,
            "author": "kcartmell",
            "created_at": "2026-08-03T15:10:00Z",
            "text": COMMENT_HTML,
        },
        {"id": 49156690, "author": "someone", "created_at": "2026-08-03T15:11:00Z",
         "text": None},                                   # deleted comment
        {"id": 49156691, "author": "other", "created_at": "2026-08-03T15:12:00Z",
         "text": "Acme | Sales Rep | NYC<p>Nothing technical here."},
    ]
}


def test_picks_who_is_hiring_not_who_wants_to_be_hired():
    """The candidate thread must never be mistaken for the jobs thread.

    They are posted seconds apart, so ordering cannot be relied on. Taking
    hits[0] would ingest job seekers advertising themselves as if they were
    open roles.
    """
    thread = hackernews.find_current_thread(SEARCH_PAYLOAD)

    assert thread is not None
    assert thread["objectID"] == "49156683"
    assert "Who is hiring" in thread["title"]


def test_returns_none_when_no_hiring_thread():
    payload = {"hits": [{"objectID": "1", "title": "Ask HN: Who wants to be hired?"}]}

    assert hackernews.find_current_thread(payload) is None


def test_parses_company_and_title_from_header(keywords):
    jobs = hackernews.normalize(ITEM_PAYLOAD, keywords)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Snout"
    assert "Senior DevOps Engineer" in job.title
    assert job.location == "Remote US"


def test_company_name_excludes_url_bare_or_parenthesised(keywords):
    """Regression: the <a> tag becomes bare URL text once tags are stripped.

    The first version only stripped a parenthesised "(https://...)", so the
    company came out as "Snout https://snout.com/".
    """
    bare = {"children": [dict(ITEM_PAYLOAD["children"][0])]}
    parens = {"children": [{
        "id": 2, "author": "a", "created_at": "2026-08-03T15:10:00Z",
        "text": "Snout (https:&#x2F;&#x2F;snout.com&#x2F;) | DevOps Engineer | Remote",
    }]}

    assert hackernews.normalize(bare, keywords)[0].company == "Snout"
    assert hackernews.normalize(parens, keywords)[0].company == "Snout"


def test_url_as_its_own_segment_does_not_become_the_title(keywords):
    """Regression, found in the deployed table rather than in a test.

    Real header from the August 2026 thread:
        GovStar | https://govstar.us | REMOTE - United States | Full-time

    The URL is its own pipe-separated segment, so cleaning only the company
    field left the job title reading "https://govstar.us | REMOTE - ...".
    """
    payload = {"children": [{
        "id": 3, "author": "a", "created_at": "2026-08-03T15:10:00Z",
        "text": ("Seeq | https:&#x2F;&#x2F;seeq.com | Staff Platform Engineer "
                 "| REMOTE<p>We run Kubernetes."),
    }]}

    job = hackernews.normalize(payload, keywords)[0]

    assert job.company == "Seeq"
    assert "http" not in job.title
    assert "Staff Platform Engineer" in job.title


def test_html_entities_are_unescaped(keywords):
    """Comment text arrives HTML-escaped; &#x2F; is a forward slash."""
    jobs = hackernews.normalize(ITEM_PAYLOAD, keywords)

    assert "&#x2F;" not in jobs[0].raw_excerpt
    assert "<a href" not in jobs[0].raw_excerpt
    assert "<p>" not in jobs[0].raw_excerpt


def test_deleted_comments_are_skipped(keywords):
    """Deleted comments come through as text: null."""
    jobs = hackernews.normalize(ITEM_PAYLOAD, keywords)

    assert all(job.external_id != "49156690" for job in jobs)


def test_url_points_at_the_comment(keywords):
    """The comment is the canonical posting and always resolves."""
    jobs = hackernews.normalize(ITEM_PAYLOAD, keywords)

    assert jobs[0].url == "https://news.ycombinator.com/item?id=49156689"


def test_matches_body_not_only_header(keywords):
    """Headers often say 'Multiple Roles' while the body names the stack."""
    payload = {"children": [{
        "id": 1, "author": "a", "created_at": "2026-08-03T15:10:00Z",
        "text": "Acme | Multiple Roles | Remote<p>We need help with Kubernetes.",
    }]}

    jobs = hackernews.normalize(payload, keywords)

    assert len(jobs) == 1
    assert "kubernetes" in jobs[0].matched_keywords

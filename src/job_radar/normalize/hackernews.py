"""Hacker News "Ask HN: Who is hiring?" threads, via the Algolia API.

This is the source with no structure at all. A posting is a *comment* — prose
written by a human, with a loose convention that the first line reads:

    Company | Role | Location | Employment type

Two calls are needed:

1.  GET /api/v1/search_by_date?tags=story,author_whoishiring
        Find the current month's thread.
2.  GET /api/v1/items/<story_id>
        Fetch its comments.

Three traps, all found by reading real responses rather than assuming:

*   `/search` is ranked by relevance, NOT date. Its first hit for "who is
    hiring" is a thread from 2016. Use `/search_by_date`.

*   Every month the same author posts TWO threads seconds apart: "Who is
    hiring?" (companies) and "Who wants to be hired?" (candidates advertising
    themselves). Taking hits[0] silently ingests job seekers as if they were
    jobs. The title must be checked.

*   Comment text is HTML with escaped entities (`&#x2F;` for `/`), `<p>` tags
    as paragraph separators and `<a href>` links. It needs unescaping before
    anything can be parsed out of it.
"""

from __future__ import annotations

import html
import logging
import re
from datetime import UTC, datetime
from typing import Any

from job_radar.fetch import fetch_json
from job_radar.models import Job, match_keywords

log = logging.getLogger("job_radar.normalize.hackernews")

SEARCH_URL = (
    "https://hn.algolia.com/api/v1/search_by_date"
    "?tags=story,author_whoishiring&hitsPerPage=10"
)
ITEM_URL = "https://hn.algolia.com/api/v1/items/{story_id}"
HN_COMMENT_URL = "https://news.ycombinator.com/item?id={comment_id}"

# "Who is hiring?" yes; "Who wants to be hired?" no.
HIRING_TITLE = re.compile(r"who\s+is\s+hiring", re.IGNORECASE)

_TAG = re.compile(r"<[^>]+>")
_HREF = re.compile(r'href="([^"]+)"')
# Matches a URL with or without surrounding parentheses.
_URL_IN_TEXT = re.compile(r"\s*\(?\s*https?://\S+?\)?(?=\s|$)")


def _clean(text: str) -> str:
    """HTML comment text -> plain text, paragraphs preserved as newlines."""
    text = re.sub(r"<p>", "\n", text)
    text = _TAG.sub("", text)
    return html.unescape(text).strip()


def _first_url(raw_html: str) -> str:
    match = _HREF.search(raw_html)
    return html.unescape(match.group(1)) if match else ""


def find_current_thread(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the newest thread whose title is actually 'Who is hiring?'."""
    for hit in payload.get("hits", []):
        if HIRING_TITLE.search(hit.get("title") or ""):
            return hit
    return None


def normalize(payload: dict[str, Any], keywords: list[str]) -> list[Job]:
    """Turn a thread's comments into Jobs."""
    jobs: list[Job] = []

    for comment in payload.get("children", []):
        raw = comment.get("text")
        if not raw:
            # Deleted or empty comments come through with text: null.
            continue

        text = _clean(raw)
        if not text:
            continue

        # Match against the whole comment: the header line often says
        # "Multiple Engineering Roles" while the body names the actual stack.
        matched = match_keywords(text, keywords)
        if not matched:
            continue

        header = text.split("\n", 1)[0].strip()
        parts = [p.strip() for p in header.split("|") if p.strip()]

        company = parts[0] if parts else (comment.get("author") or "unknown")
        # Posters put their URL next to the company name, sometimes in
        # parentheses and sometimes bare. Both end up as plain text once the
        # <a> tag is stripped, so strip any URL rather than only the
        # parenthesised form.
        company = _URL_IN_TEXT.sub("", company).strip(" |-—–")

        title = " | ".join(parts[1:3]) if len(parts) > 1 else header
        location = parts[2] if len(parts) > 2 else ""

        created = comment.get("created_at")
        try:
            posted = (
                datetime.fromisoformat(created).astimezone(UTC)
                if created
                else datetime.now(UTC)
            )
        except ValueError:
            posted = datetime.now(UTC)

        jobs.append(
            Job(
                source="hackernews",
                external_id=str(comment.get("id")),
                title=(title or header)[:300],
                company=company[:200],
                # Link to the comment itself: it is the canonical posting and
                # always resolves, unlike a company URL that may 404 later.
                url=HN_COMMENT_URL.format(comment_id=comment.get("id")),
                location=location[:200],
                posted_at=posted,
                matched_keywords=matched,
                raw_excerpt=text[:500],
            )
        )

    return jobs


def collect(keywords: list[str]) -> list[Job]:
    thread = find_current_thread(fetch_json(SEARCH_URL))
    if thread is None:
        log.warning("no 'Who is hiring' thread found")
        return []

    story_id = thread["objectID"]
    log.info(
        "found hiring thread",
        extra={"story_id": story_id, "title": thread.get("title")},
    )
    return normalize(fetch_json(ITEM_URL.format(story_id=story_id)), keywords)

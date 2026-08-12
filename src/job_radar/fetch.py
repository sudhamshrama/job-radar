"""HTTP fetching, using only the standard library.

No `requests`. Every third-party dependency in a Lambda means building a
deployment package, and a package built on this arm64 Mac can break on Lambda's
x86_64 runtime. `urllib` ships with the runtime, so the zip stays pure Python
and there is nothing to compile.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

log = logging.getLogger("job_radar.fetch")

# RemoteOK returns 403 to the default urllib agent. Identifying the client is
# also the polite thing to do when calling someone's public API on a schedule.
USER_AGENT = "job-radar/0.1 (+https://github.com/sudhamshrama/job-radar)"

DEFAULT_TIMEOUT = 15
MAX_ATTEMPTS = 3


class FetchError(Exception):
    """A source could not be fetched after retries."""


def fetch_json(url: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    """GET a URL and parse JSON, retrying transient failures.

    Retries 5xx and network errors with exponential backoff. Does NOT retry
    4xx: a 404 board token or a 403 will fail identically every time, and
    retrying just delays the inevitable while burning Lambda duration.
    """
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as exc:
            if 400 <= exc.code < 500:
                raise FetchError(f"{url} returned {exc.code}") from exc
            last_error = exc

        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc

        if attempt < MAX_ATTEMPTS:
            backoff = 2 ** (attempt - 1)
            log.warning(
                "fetch failed, retrying",
                extra={"url": url, "attempt": attempt, "backoff_s": backoff,
                       "error": str(last_error)},
            )
            time.sleep(backoff)

    raise FetchError(f"{url} failed after {MAX_ATTEMPTS} attempts: {last_error}")

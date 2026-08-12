"""Source-specific normalizers.

Each module turns one source's response into a list of `Job` objects. They share
no structure because the sources share no structure — that is the point of the
source mix chosen in ADR 0004.
"""

from job_radar.normalize import greenhouse, hackernews, remoteok

NORMALIZERS = {
    "greenhouse": greenhouse,
    "remoteok": remoteok,
    "algolia": hackernews,
}

__all__ = ["NORMALIZERS", "greenhouse", "remoteok", "hackernews"]

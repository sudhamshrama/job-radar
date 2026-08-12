"""Loading config/sources.json.

Board tokens are configuration, not code — a dead board should be a config edit,
not a deploy of new logic. The file is bundled into the Lambda zip and read from
`/var/task/config/sources.json` at runtime.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = "/var/task/config/sources.json"


@dataclass
class Config:
    match_keywords: list[str]
    sources: list[dict[str, Any]]

    def source(self, source_id: str) -> dict[str, Any] | None:
        for src in self.sources:
            if src.get("id") == source_id:
                return src
        return None


def _locate() -> Path:
    override = os.environ.get("SOURCES_CONFIG")
    if override:
        return Path(override)

    packaged = Path(DEFAULT_CONFIG_PATH)
    if packaged.exists():
        return packaged

    # Local runs and tests: walk up to the repo root.
    return Path(__file__).resolve().parents[2] / "config" / "sources.json"


def load(path: str | Path | None = None) -> Config:
    target = Path(path) if path else _locate()
    with open(target, encoding="utf-8") as handle:
        raw = json.load(handle)

    return Config(
        match_keywords=raw.get("match_keywords", []),
        # Keys beginning with "_" are documentation, not sources.
        sources=[s for s in raw.get("sources", []) if not s.get("id", "").startswith("_")],
    )

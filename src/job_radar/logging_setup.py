"""Structured JSON logging for Lambda.

CloudWatch Logs Insights can query JSON fields directly, but only if every line
is valid JSON. A single plain-text line from a library logger breaks the query,
which is easy to miss because the logs still *look* fine.

In url-shortener the same failure appeared as uvicorn's own loggers bypassing
the configured JSON formatter. The fix is the same: reconfigure the root
handler rather than adding a new one, so records from libraries flow through
the formatter too.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

_RESERVED = {
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Lambda injects the request id onto the record.
        request_id = getattr(record, "aws_request_id", None)
        if request_id:
            payload["request_id"] = request_id

        # Anything passed via logger.info("...", extra={...}) lands as an
        # attribute on the record. Promote those to top-level JSON fields so
        # they are queryable in Logs Insights.
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload.setdefault(key, value)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure() -> logging.Logger:
    """Install the JSON formatter on the root logger and return ours.

    Lambda pre-installs a handler on the root logger. Adding another would
    duplicate every line, so replace the formatter on the existing handlers
    instead of appending.
    """
    root = logging.getLogger()
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    root.setLevel(level)

    if root.handlers:
        for handler in root.handlers:
            handler.setFormatter(JsonFormatter())
    else:
        # Local runs and tests have no pre-installed handler.
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)

    return logging.getLogger("job_radar")

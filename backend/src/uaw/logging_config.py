"""Process-wide logging: plain text for humans, or one JSON object per line.

Every record carries the ID of the HTTP request being served (``request_id``), taken
from a context variable that ``RequestContextMiddleware`` sets. asyncio copies it into
the tasks a request starts, so the logs of a background import carry the ID of the
request that queued it.
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from uaw.config import LogFormat, LogLevel

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] [%(request_id)s] %(message)s"

request_id_var: ContextVar[str | None] = ContextVar("uaw_request_id", default=None)

# Attributes every LogRecord has; anything else was passed with ``extra=``.
_STANDARD_ATTRIBUTES = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        entry.update(
            (key, value) for key, value in vars(record).items() if key not in _STANDARD_ATTRIBUTES
        )
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str, ensure_ascii=False)


def configure_logging(level: LogLevel, log_format: LogFormat = "text") -> None:
    """Configure root logging once for the whole process."""
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(JsonFormatter() if log_format == "json" else logging.Formatter(LOG_FORMAT))
    logging.basicConfig(level=level, handlers=[handler], force=True)

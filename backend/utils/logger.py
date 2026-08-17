import contextvars
import json
import logging
import sys
import uuid
from datetime import datetime, timezone

# One ContextVar per async task/request — set by middleware, read by the filter below. WebSocket calls inherit this for the full call duration.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def generate_request_id() -> str:
    return uuid.uuid4().hex[:8]


class _JsonFormatter(logging.Formatter):
    """Emit each log record as a single JSON line.

    Standard fields: timestamp, level, logger, request_id, message.
    Extra keyword arguments passed via `extra={"key": value}` are merged in
    at the top level so Loki / Datadog can filter on them directly.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        # Merge any structured fields passed via extra={}
        for key, value in record.__dict__.items():
            if key not in _LOGGING_RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# Fields that are part of LogRecord internals — never surface these in JSON output.
_LOGGING_RESERVED = frozenset(
    logging.LogRecord(
        name="", level=0, pathname="", lineno=0, msg="", args=(), exc_info=None
    ).__dict__.keys()
    | {"message", "asctime"}
)


class _RequestIdFilter(logging.Filter):
    """Injects the current request_id into every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        return True


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JsonFormatter())
        handler.addFilter(_RequestIdFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# Root logger setup
root_logger = setup_logger("vapi_backend")

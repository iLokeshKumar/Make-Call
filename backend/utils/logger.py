import contextvars
import logging
import sys
import uuid

# One ContextVar per async task/request — set by middleware, read by the filter below. WebSocket calls inherit this for the full call duration.
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def generate_request_id() -> str:
    return uuid.uuid4().hex[:8]


class _RequestIdFilter(logging.Filter):
    """Injects the current request_id into every LogRecord."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get("-")
        return True


def setup_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] [req:%(request_id)s] %(message)s"
        )
        handler.setFormatter(formatter)
        handler.addFilter(_RequestIdFilter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


# Root logger setup
root_logger = setup_logger("vapi_backend")

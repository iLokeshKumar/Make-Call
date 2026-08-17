from __future__ import annotations

import logging
import os
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)

_TRACING_ENABLED: bool = False


def configure_tracing() -> bool:

    global _TRACING_ENABLED

    api_key = os.getenv("LANGCHAIN_API_KEY", "").strip()
    tracing_on = os.getenv("LANGCHAIN_TRACING_V2", "").lower() in ("1", "true", "yes")
    project = os.getenv("LANGCHAIN_PROJECT", "rio-crm")

    if not tracing_on:
        logger.info("[Tracing] LANGCHAIN_TRACING_V2 not set — LangSmith tracing disabled.")
        return False

    if not api_key:
        logger.warning("[Tracing] LANGCHAIN_TRACING_V2=true but LANGCHAIN_API_KEY missing — tracing disabled.")
        return False

    try:
        import langsmith
        os.environ.setdefault("LANGCHAIN_PROJECT", project)
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        _TRACING_ENABLED = True
        logger.info("[Tracing] LangSmith tracing enabled. Project=%s", project)
        return True
    except ImportError:
        logger.warning(
            "[Tracing] langsmith package not installed. Run: pip install langsmith"
        )
        return False
    except Exception as exc:
        logger.warning("[Tracing] LangSmith setup failed: %s", exc)
        return False


def is_tracing_enabled() -> bool:
    """Return True if LangSmith tracing is active."""
    return _TRACING_ENABLED


def get_run_metadata() -> dict[str, Any]:
    """
    Build a metadata dict to attach to LangSmith runs.

    Includes the current HTTP request ID (from utils.logger ContextVar)
    and the deployment environment.
    """
    meta: dict[str, Any] = {
        "env": os.getenv("APP_ENV", "production"),
        "service": "rio-crm",
    }
    try:
        from utils.logger import request_id_var
        req_id = request_id_var.get(None)
        if req_id:
            meta["request_id"] = req_id
    except Exception:
        pass
    return meta


def traceable(
    name: str | None = None,
    run_type: str = "chain",
    tags: list[str] | None = None,
):
    """
    Decorator that wraps a function with LangSmith tracing when enabled.

    Falls back to a no-op wrapper when langsmith is not installed or tracing
    is disabled, so agent code never breaks in environments without tracing.

    Args:
        name: Display name in LangSmith UI (defaults to function name).
        run_type: LangSmith run type — "chain", "llm", "tool", "retriever".
        tags: Optional tags shown in LangSmith UI.

    Example::

        @traceable(name="pre_call_researcher", tags=["pre_call"])
        def researcher_node(state: dict) -> dict:
            ...
    """
    def decorator(fn: Callable) -> Callable:
        if not _TRACING_ENABLED:
            return fn  # zero overhead when tracing is off

        try:
            from langsmith import traceable as _ls_traceable
            traced = _ls_traceable(
                name=name or fn.__name__,
                run_type=run_type,
                tags=tags or [],
                metadata=get_run_metadata(),
            )(fn)
            @wraps(fn)
            def wrapper(*args, **kwargs):
                return traced(*args, **kwargs)
            return wrapper
        except Exception:
            return fn

    return decorator


def traceable_async(
    name: str | None = None,
    run_type: str = "chain",
    tags: list[str] | None = None,
):
    """
    Async version of @traceable for async node functions and workflow runners.

    Args:
        name: Display name in LangSmith UI.
        run_type: "chain", "llm", "tool", or "retriever".
        tags: Optional tags.
    """
    def decorator(fn: Callable) -> Callable:
        if not _TRACING_ENABLED:
            return fn

        try:
            from langsmith import traceable as _ls_traceable
            traced = _ls_traceable(
                name=name or fn.__name__,
                run_type=run_type,
                tags=tags or [],
                metadata=get_run_metadata(),
            )(fn)
            @wraps(fn)
            async def wrapper(*args, **kwargs):
                return await traced(*args, **kwargs)
            return wrapper
        except Exception:
            return fn

    return decorator

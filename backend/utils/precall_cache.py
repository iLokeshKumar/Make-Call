"""
Pre-call context cache — stores run_pre_call() results in-process with TTL.

The dialer_service writes here after running the pre-call workflow;
the voice_pipeline reads from here when the call connects so KB context
and ICP data are available instantly without a second DB round-trip.

Key:   (company_id, lead_id)
TTL:   10 minutes (enough for any call setup delay)
Store: icp_score, lead_data, kb_context, interaction_history
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Any

_TTL_SECONDS: int = 600  # 10 minutes
_cache: dict[tuple[int, int], tuple[float, dict[str, Any]]] = {}
_lock = Lock()


def put(company_id: int, lead_id: int, data: dict[str, Any]) -> None:
    """Store pre-call results for a lead.

    Args:
        company_id: Tenant ID.
        lead_id: Lead ID.
        data: Dict returned by agents.orchestrator.run_pre_call().
    """
    with _lock:
        _cache[(company_id, lead_id)] = (time.monotonic(), data)


def get(company_id: int, lead_id: int) -> dict[str, Any] | None:
    """Retrieve pre-call results if still within TTL.

    Returns None if not found or expired.
    """
    with _lock:
        entry = _cache.get((company_id, lead_id))
        if entry is None:
            return None
        stored_at, data = entry
        if time.monotonic() - stored_at > _TTL_SECONDS:
            del _cache[(company_id, lead_id)]
            return None
        return data


def evict(company_id: int, lead_id: int) -> None:
    """Remove a cache entry after it has been consumed."""
    with _lock:
        _cache.pop((company_id, lead_id), None)


def format_kb_context_for_prompt(data: dict[str, Any]) -> str:
    """
    Convert the kb_context list from run_pre_call() into a prompt-injectable string.

    Returns an empty string if no KB context was retrieved.
    """
    kb = data.get("kb_context", [])
    if not kb:
        return ""
    lines = ["\n\n### [KNOWLEDGE BASE CONTEXT]",
             "Use the following company knowledge to handle objections and questions:"]
    for chunk in kb[:6]:          # cap at 6 chunks to stay within token budget
        if isinstance(chunk, str) and chunk.strip():
            lines.append(f"- {chunk.strip()[:400]}")
    return "\n".join(lines)

"""Outreacher agent — channel selection + dispatch for qualified leads.

Week 7.2 of the roadmap splits the monolithic ISM orchestrator into three
focused agents (researcher, outreacher, closer). The outreacher's job is to
take a qualified lead and decide how to reach them next: pick the channel
(call / WhatsApp / email), respect cooldowns + opt-outs, and enqueue the
actual send through the AgentTask queue.

This module is the public entry point registered in agents/orchestrator.py
as `"outreacher"`. The channel-pick + dispatch logic still lives inside
agents/ism_orchestrator.py today — we expose it here via thin re-exports so:

  * `run_agent("outreacher", ...)` routes correctly from the agent worker.
  * The researcher's qualify path can enqueue an `outreacher` AgentTask by
    name; the worker unpacks it and calls `run()` below.
  * Tests can stub `agents.outreacher.pick_channel` / `dispatch_*` cleanly.
  * The 845-line ism_orchestrator refactor (move code, don't just re-export)
    can land as a follow-up without breaking callers.

When the real code move happens, everything outside this module keeps
importing `agents.outreacher` and nothing changes.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session, select

from agents.ism_orchestrator import (
    _dispatch_call as _ism_dispatch_call,
    _dispatch_email as _ism_dispatch_email,
    _dispatch_whatsapp as _ism_dispatch_whatsapp,
    _pick_channel as _ism_pick_channel,
)
from database import engine
from models.models import Lead, utc_now

logger = logging.getLogger(__name__)


# Public function names the rest of the app should use.  Thin aliases today;
# ready to take over as the canonical implementation when the code moves.

def pick_channel(session: Session, company_id: int, lead: Lead, stage: str) -> str | None:
    return _ism_pick_channel(session, company_id, lead, stage)


def dispatch_call(session: Session, company_id: int, actor_user_id: int, lead: Lead, stage: str) -> dict:
    return _ism_dispatch_call(session, company_id, actor_user_id, lead, stage)


def dispatch_whatsapp(session: Session, company_id: int, actor_user_id: int, lead: Lead, stage: str) -> dict:
    return _ism_dispatch_whatsapp(session, company_id, actor_user_id, lead, stage)


def dispatch_email(session: Session, company_id: int, actor_user_id: int, lead: Lead, stage: str) -> dict:
    return _ism_dispatch_email(session, company_id, actor_user_id, lead, stage)


_CHANNEL_NAMES = ("call", "whatsapp", "email")


def _resolve_dispatcher(channel: str):
    """Look up the dispatcher by name at call time.

    Going through `globals()` instead of a pre-built dict lets tests monkeypatch
    `agents.outreacher.dispatch_whatsapp` and still see their stub invoked —
    a captured-reference dict would keep the original functions.
    """
    if channel not in _CHANNEL_NAMES:
        return None
    return globals().get(f"dispatch_{channel}")


def _load_lead(session: Session, company_id: int, lead_id: int) -> Lead | None:
    return session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
            Lead.deleted_at.is_(None),
        )
    ).first()


def _stamp_lead_after_dispatch(
    session: Session,
    lead: Lead,
    actor_user_id: int,
    channel: str,
) -> None:
    """Persist the 'just dispatched' fields.  Never crashes the dispatch.

    Matches the pattern in ism_orchestrator so downstream consumers (call-monitor
    UI, kanban board) see fresh `last_outreach_at` immediately.
    """
    try:
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[outreacher] post-dispatch stamp failed: %s", exc)


async def run(
    company_id: int,
    actor_user_id: int = 0,
    lead_id: int | None = None,
    stage: str | None = None,
    **_kwargs: Any,
) -> dict:
    """Pick a channel for a qualified lead + enqueue the send.

    Matches the signature convention used by the orchestrator dispatcher
    (`run_agent("outreacher", ..., lead_id=..., stage=...)`).

    Returns a result dict with keys:
      * `lead_id`, `stage`
      * `channel` (or `None` + `skipped=True` + `skip_reason`)
      * Dispatch-specific extras (`call_task_id`, `agent_task_id`, etc.)
    """
    if not lead_id:
        return {"error": "lead_id required", "skipped": True}

    with Session(engine) as session:
        lead = _load_lead(session, company_id, lead_id)
        if lead is None:
            return {"lead_id": lead_id, "skipped": True, "skip_reason": "lead_not_found"}

        effective_stage = stage or lead.ism_stage or "new"
        # Look the name up fresh via globals() so tests can monkeypatch the
        # module-level name.
        _pick = globals().get("pick_channel")
        channel = _pick(session, company_id, lead, effective_stage) if _pick else None

        if channel is None:
            return {
                "lead_id": lead_id,
                "stage": effective_stage,
                "skipped": True,
                "skip_reason": "all_channels_blocked",
            }

        dispatcher = _resolve_dispatcher(channel)
        if dispatcher is None:
            return {
                "lead_id": lead_id,
                "stage": effective_stage,
                "skipped": True,
                "skip_reason": f"no_dispatcher_for_{channel}",
            }

        try:
            result = dispatcher(session, company_id, actor_user_id, lead, effective_stage)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[outreacher] dispatch failed for lead=%s channel=%s: %s", lead_id, channel, exc)
            return {
                "lead_id": lead_id,
                "stage": effective_stage,
                "channel": channel,
                "error": str(exc),
                "skipped": False,
            }

        _stamp_lead_after_dispatch(session, lead, actor_user_id, channel)

        return {
            "lead_id": lead_id,
            "stage": effective_stage,
            "channel": channel,
            "skipped": False,
            **result,
        }

"""Send-agent executor — dispatches state-changing send actions (email, whatsapp, quote).

Invoked by the automation worker via `orchestrator.run_agent(agent_name="send", ...)`
when it claims an AgentTask whose `assigned_agent == "send"`. The `task_type`
field (from AgentTask.input_json) selects which underlying sender to call.

Supported task_types:
  - send_email     → services.communication.communication_service.send_email_to_lead
  - send_whatsapp  → services.communication.communication_service.send_whatsapp_to_lead
  - send_quote     → services.communication.communication_service.send_quote_to_lead

The agent opens its own DB session (the worker's session is committed per
task, so a fresh session avoids transaction-boundary surprises). Return value
is a JSON-serializable dict written to AgentTask.output_json.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session

from database import engine
from services.agent.task_metrics import build_metrics, merge_metrics_into_output, time_block

logger = logging.getLogger(__name__)


async def run(
    *,
    company_id: int,
    actor_user_id: int = 0,
    lead_id: int | None = None,
    task_type: str | None = None,
    # send_email / send_whatsapp payload
    subject: str = "",
    body: str = "",
    cta_url: str = "",
    cta_label: str = "",
    # send_quote / send_proposal payload
    quote_id: int | None = None,
    proposal_id: int | None = None,
    proposal_document_id: int | None = None,
    channels: list | None = None,
    message: str | None = None,
    **_unused: Any,    # absorb any extra keys without crashing
) -> dict:
    """Entry point for orchestrator.run_agent.

    Every field is keyword-only — orchestrator.run_agent spreads
    AgentTask.input_json as kwargs, and we want strict signature validation
    rather than accidental positional passing.
    """
    with time_block() as t:
        if task_type is None:
            result = {"ok": False, "error": "send agent invoked without task_type"}
        else:
            handler = _HANDLERS.get(task_type)
            if handler is None:
                result = {"ok": False, "error": f"send agent: unknown task_type {task_type!r}"}
            else:
                payload = {
                    "subject": subject,
                    "body": body,
                    "cta_url": cta_url,
                    "cta_label": cta_label,
                    "quote_id": quote_id,
                    "proposal_id": proposal_id,
                    "proposal_document_id": proposal_document_id,
                    "channels": channels,
                    "message": message,
                }
                try:
                    with Session(engine) as session:
                        result = handler(session, company_id, actor_user_id, lead_id, payload)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("[send_agent] %s failed for lead=%s: %s", task_type, lead_id, exc)
                    result = {"ok": False, "error": str(exc), "task_type": task_type}

    # Send executors don't call LLMs — only latency matters. The Performance
    # dashboard reads this same metrics shape from every task_type.
    return merge_metrics_into_output(result, build_metrics(latency_ms=t["ms"]))


# Handlers — one per task_type. Each is synchronous because the underlying
# sender services are synchronous. The agent's `run` is async so it fits the
# orchestrator.run_agent contract.

def _handle_send_email(session, company_id, actor_user_id, lead_id, payload) -> dict:
    from services.communication.communication_service import send_email_to_lead
    result = send_email_to_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead_id,
        subject=payload["subject"],
        body=payload["body"],
        cta_url=payload["cta_url"],
        cta_label=payload["cta_label"],
    )
    return {"ok": True, "channel": "email", "result": result}


def _handle_send_whatsapp(session, company_id, actor_user_id, lead_id, payload) -> dict:
    from services.communication.communication_service import send_whatsapp_to_lead
    from services.leads.opt_out_service import is_lead_opted_out

    # Enforce opt-out before dispatching any WhatsApp message
    if lead_id is not None and is_lead_opted_out(session, company_id, lead_id, "whatsapp"):
        logger.warning(
            "[send_agent] WhatsApp blocked — lead %s opted out (company=%s)", lead_id, company_id
        )
        return {"ok": False, "error": "Lead has opted out of WhatsApp", "channel": "whatsapp"}

    # communication_service accepts `body` (not `message`) — stay consistent
    body = payload["body"] or payload["message"] or ""
    result = send_whatsapp_to_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead_id,
        body=body,
    )
    return {"ok": True, "channel": "whatsapp", "result": result}


def _handle_send_quote(session, company_id, actor_user_id, lead_id, payload) -> dict:
    from services.communication.communication_service import send_quote_to_lead
    if payload["quote_id"] is None:
        return {"ok": False, "error": "send_quote requires quote_id"}
    channels = payload["channels"] or ["email"]
    result = send_quote_to_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        quote_id=payload["quote_id"],
        channels=channels,
        subject=payload["subject"] or None,
        message=payload["message"],
    )
    return {"ok": True, "channel": "quote", "result": result}


def _handle_send_proposal(session, company_id, actor_user_id, lead_id, payload) -> dict:
    from services.communication.communication_service import send_quote_to_lead
    from services.proposal.proposal_service import mark_proposal_sent
    from services.quote.quote_service import mark_quote_status
    from models.models import ProposalDocument

    if payload["proposal_id"] is None:
        return {"ok": False, "error": "send_proposal requires proposal_id"}
    if payload["quote_id"] is None:
        return {"ok": False, "error": "send_proposal requires quote_id"}

    channels = payload["channels"] or ["email"]
    attachment_paths: list[str] = []
    if payload["proposal_document_id"] is not None:
        doc = session.get(ProposalDocument, payload["proposal_document_id"])
        if doc and doc.company_id == company_id and doc.pdf_path:
            attachment_paths.append(doc.pdf_path)
    result = send_quote_to_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        quote_id=payload["quote_id"],
        channels=channels,
        subject=payload["subject"] or None,
        message=payload["message"],
        attachment_paths=attachment_paths,
    )
    mark_proposal_sent(
        session=session,
        company_id=company_id,
        proposal_id=payload["proposal_id"],
        document_id=payload["proposal_document_id"],
        actor_user_id=actor_user_id,
    )
    mark_quote_status(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        quote_id=payload["quote_id"],
        status="sent",
    )
    return {
        "ok": True,
        "channel": "proposal",
        "proposal_id": payload["proposal_id"],
        "proposal_document_id": payload["proposal_document_id"],
        "result": result,
    }


_HANDLERS = {
    "send_email": _handle_send_email,
    "send_whatsapp": _handle_send_whatsapp,
    "send_quote": _handle_send_quote,
    "send_proposal": _handle_send_proposal,
}

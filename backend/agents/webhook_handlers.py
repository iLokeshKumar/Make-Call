"""Webhook handlers agent — durable executors for inbound and status events.

Part of the "Thin Webhook Wrapper" pattern (Roadmap Week 2.3).
These executors are called by the worker when it claims an AgentTask
enqueued by the route handlers.
"""
from __future__ import annotations

import logging
from typing import Any
from sqlmodel import Session, select
from database import engine as db_engine
from models.models import Interaction, User, CallTask, Lead, utc_now
from services.communication.inbound_whatsapp_service import ingest_whatsapp_webhook_event
from services.communication.inbound_email_service import ingest_email_webhook_event
from services.call.outcome_service import apply_call_outcome, apply_lead_only_outcome

logger = logging.getLogger(__name__)

async def run(
    *,
    company_id: int,
    task_type: str,
    input_json: dict[str, Any],
    actor_user_id: int = 0,
    **_unused: Any,
) -> dict:
    """Dispatch to specific handler based on task_type."""
    payload = input_json.get("payload", {})
    
    with Session(db_engine) as session:
        if task_type == "process_inbound_whatsapp":
            return ingest_whatsapp_webhook_event(session, payload)
            
        elif task_type == "process_whatsapp_status":
            return _handle_whatsapp_status(session, payload)
            
        elif task_type == "process_inbound_email":
            forced_company_id = input_json.get("forced_company_id")
            return ingest_email_webhook_event(session, payload, forced_company_id=forced_company_id)
            
        elif task_type == "process_call_status":
            return _handle_call_status(session, payload, input_json.get("query_params", {}))
            
        else:
            logger.warning("[webhook_handlers] Unknown task_type: %s", task_type)
            return {"status": "error", "message": f"Unknown task_type: {task_type}"}

def _handle_whatsapp_status(session: Session, payload: dict) -> dict:
    """Logic moved from tracking.py:whatsapp_status_tracking."""
    provider_message_sid = str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip() or None
    provider_status = str(payload.get("MessageStatus") or payload.get("SmsStatus") or "").strip().lower() or None

    if not provider_message_sid or not provider_status:
        return {"status": "ignored", "reason": "missing_sid_or_status"}

    interaction = session.exec(
        select(Interaction).where(
            Interaction.metadata_json["provider_message_sid"].as_string() == provider_message_sid
        )
    ).first()

    if interaction:
        metadata = dict(interaction.metadata_json or {})
        metadata.setdefault("provider_events", []).append(dict(payload))
        metadata["provider_message_sid"] = provider_message_sid
        metadata["provider_message_status"] = provider_status
        interaction.metadata_json = metadata
        interaction.updated_at = utc_now()

        delivery_status_map = {
            "queued": "pending",
            "accepted": "sent",
            "sent": "sent",
            "delivered": "delivered",
            "read": "read",
            "failed": "failed",
            "undelivered": "failed",
        }
        if provider_status in delivery_status_map:
            interaction.delivery_status = delivery_status_map[provider_status]
            if provider_status in {"failed", "undelivered"}:
                interaction.status = "failed"
            elif provider_status in {"sent", "delivered", "read"}:
                interaction.status = "completed"

        session.add(interaction)
        session.commit()
        return {"status": "status_recorded", "interaction_id": interaction.id}
    
    return {"status": "ignored", "reason": "interaction_not_found"}

def _handle_call_status(session: Session, payload: dict, query_params: dict) -> dict:
    """Logic moved from telephony.py:twilio_status_callback."""
    CallStatus = payload.get("CallStatus")
    CallSid = payload.get("CallSid")
    
    call_task_id = query_params.get("call_task_id")
    interaction_id = query_params.get("interaction_id")
    user_id = query_params.get("user_id")

    actor_user = session.get(User, int(user_id)) if user_id and str(user_id).isdigit() else None
    db_interaction = None
    if interaction_id and str(interaction_id).isdigit():
        db_interaction = session.get(Interaction, int(interaction_id))
        if db_interaction:
            db_interaction.metadata_json = {
                **(db_interaction.metadata_json or {}),
                "call_sid": CallSid,
                "provider_call_status": CallStatus,
            }
            db_interaction.updated_at = utc_now()
            if actor_user:
                db_interaction.updated_by = actor_user.id
            session.add(db_interaction)
            session.commit()

    # Outcome processing only for terminal state
    TERMINAL = {"completed", "busy", "no-answer", "failed", "canceled"}
    if CallStatus not in TERMINAL:
        return {"status": "tracked", "call_status": CallStatus}

    if db_interaction and db_interaction.status != "ended":
        db_interaction.status = "ended"
        db_interaction.ended_at = utc_now()
        db_interaction.updated_at = utc_now()
        session.add(db_interaction)
        session.commit()

    if not actor_user:
        return {"status": "tracked", "call_status": CallStatus}

    transcript = db_interaction.transcript if db_interaction else None
    interaction_id_int = int(interaction_id) if interaction_id and str(interaction_id).isdigit() else None
    has_call_task = bool(call_task_id and str(call_task_id).isdigit() and int(call_task_id) != 0)

    if has_call_task:
        result = apply_call_outcome(
            session=session,
            company_id=actor_user.company_id,
            actor_user_id=actor_user.id,
            task_id=int(call_task_id),
            interaction_id=interaction_id_int,
            raw_status=CallStatus,
            transcript=transcript,
        )
        return {"status": "processed", "result": result}

    lead_id_from_interaction = db_interaction.lead_id if db_interaction else None
    if not lead_id_from_interaction:
        return {"status": "tracked", "call_status": CallStatus}

    result = apply_lead_only_outcome(
        session=session,
        company_id=actor_user.company_id,
        actor_user_id=actor_user.id,
        lead_id=lead_id_from_interaction,
        interaction_id=interaction_id_int,
        raw_status=CallStatus,
        transcript=transcript,
    )
    return {"status": "processed_lead_only", "result": result}

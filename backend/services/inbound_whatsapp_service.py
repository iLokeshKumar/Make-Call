"""
Inbound WhatsApp webhook ingestion — status updates and reply processing.
Handles: delivery status tracking, reply intent classification,
lead state updates, campaign progression, auto-replies.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from models.models import CallTask, CampaignRecipient, CompanySetting, Interaction, Lead, utc_now
from services.engagement_service import record_engagement_event, record_whatsapp_event
from services.opt_out_service import is_lead_opted_out, unsubscribe_lead
from utils.phone import normalize_phone

# ── Intent keyword sets ───────────────────────────────────────────────────────

OPT_OUT_TERMS      = {"stop", "unsubscribe", "remove me", "stop messaging", "stop whatsapp", "do not message"}
NOT_INTERESTED_TERMS = {"not interested", "no thanks", "not now", "not looking", "not required"}
CALLBACK_TERMS     = {"call me", "call back", "callback", "ring me", "speak later"}
QUOTE_TERMS        = {"quote", "pricing", "price", "proposal", "estimate"}
INTERESTED_TERMS   = {"interested", "yes", "sounds good", "tell me more", "share details", "details please"}

_AUTO_REPLY_TEMPLATES: dict[str, str] = {
    "interested":              "Thanks for your interest! Our team will reach out to you shortly.",
    "callback_requested":      "Got it! We've scheduled a callback for you. We'll call you soon.",
    "quote_requested_sent":    "Your quote is on its way! Please check your messages.",
    "quote_requested_pending": "Thanks! We're preparing a custom quote for you and will send it shortly.",
    "neutral":                 "Thanks for reaching out! Our team will get back to you soon.",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalize_channel_phone(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.replace("whatsapp:", "").strip()
    if not stripped:
        return None
    return normalize_phone(stripped)


def _resolve_company_id_by_whatsapp_number(session: Session, to_number: str | None) -> int | None:
    normalized_to = _normalize_channel_phone(to_number)
    if not normalized_to:
        return None
    settings = session.exec(
        select(CompanySetting).where(
            CompanySetting.key.in_(["WHATSAPP_NUMBER", "WHATSAPP_NUMBER_FROM"])
        )
    ).all()
    for setting in settings:
        if _normalize_channel_phone(setting.value) == normalized_to:
            return setting.company_id
    return None


def resolve_company_id_by_whatsapp_number(session: Session, to_number: str | None) -> int | None:
    return _resolve_company_id_by_whatsapp_number(session, to_number)


def _get_whatsapp_interaction_by_provider_sid(session: Session, provider_message_sid: str) -> Interaction | None:
    interactions = session.exec(select(Interaction).where(Interaction.channel == "whatsapp")).all()
    for interaction in interactions:
        metadata = interaction.metadata_json or {}
        if metadata.get("provider_message_sid") == provider_message_sid:
            return interaction
    return None


def _is_whatsapp_auto_reply_enabled(session: Session, company_id: int) -> bool:
    setting = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == "WHATSAPP_AUTO_REPLY_ENABLED",
        )
    ).first()
    if setting is None:
        return True  # enabled by default
    return str(setting.value).lower() not in {"false", "0", "no", "off"}


def _send_whatsapp_auto_reply(
    session: Session,
    company_id: int,
    lead_id: int,
    actor_user_id: int | None,
    intent: str,
    quote_result: dict[str, Any],
) -> dict[str, Any] | None:
    if intent in {"opt_out", "not_interested"}:
        return None
    if not _is_whatsapp_auto_reply_enabled(session, company_id):
        return None

    if intent == "quote_requested":
        quote_sent = quote_result.get("status") in {"sent", "quote_created_and_sent"}
        template_key = "quote_requested_sent" if quote_sent else "quote_requested_pending"
    else:
        template_key = intent if intent in _AUTO_REPLY_TEMPLATES else "neutral"

    body = _AUTO_REPLY_TEMPLATES[template_key]
    try:
        from services.communication_service import send_whatsapp_to_lead
        return send_whatsapp_to_lead(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id or 1,
            lead_id=lead_id,
            body=body,
        )
    except Exception:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "WhatsApp auto-reply failed: company=%d lead=%d intent=%s",
            company_id, lead_id, intent,
        )
        return None


def classify_reply_intent(body: str) -> str:
    lowered = (body or "").strip().lower()
    if not lowered:
        return "neutral"
    if any(term in lowered for term in OPT_OUT_TERMS):
        return "opt_out"
    if any(term in lowered for term in NOT_INTERESTED_TERMS):
        return "not_interested"
    if any(term in lowered for term in CALLBACK_TERMS):
        return "callback_requested"
    if any(term in lowered for term in QUOTE_TERMS):
        return "quote_requested"
    if any(term in lowered for term in INTERESTED_TERMS):
        return "interested"
    return "neutral"


def _find_active_whatsapp_campaign_recipient(
    session: Session,
    company_id: int,
    lead_id: int,
) -> CampaignRecipient | None:
    recipients = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.company_id == company_id,
            CampaignRecipient.lead_id == lead_id,
            CampaignRecipient.status.in_(["active", "pending"]),
        ).order_by(CampaignRecipient.updated_at.desc())
    ).all()
    if not recipients:
        return None

    from services.campaign_service import get_current_step
    for recipient in recipients:
        step = get_current_step(session, company_id, recipient.campaign_id, recipient.current_step)
        if step and step.channel == "whatsapp":
            return recipient
    return None


def _update_lead_for_whatsapp_reply(
    session: Session,
    lead: Lead,
    actor_user_id: int | None,
    body: str,
    intent: str,
) -> dict[str, Any]:
    lead.updated_at = utc_now()
    if actor_user_id is not None:
        lead.updated_by = actor_user_id

    created_call_task: CallTask | None = None
    if intent == "opt_out":
        unsubscribe_lead(
            session=session,
            company_id=lead.company_id,
            actor_user_id=actor_user_id,
            lead_id=lead.id,
            channel="whatsapp",
            reason="Opt out via WhatsApp reply",
        )
        lead.qualification_status = "not_interested"
        lead.next_action = "close_lost"
        lead.next_action_due_at = None
    elif intent == "not_interested":
        lead.status = "closed_lost"
        lead.qualification_status = "not_interested"
        lead.next_action = "close_lost"
        lead.next_action_due_at = None
    elif intent == "quote_requested":
        lead.status = "contacted"
        lead.qualification_status = "qualified"
        lead.next_action = "send_quote"
        lead.next_action_due_at = utc_now()
        lead.last_outreach_at = utc_now()
        lead.product_interest = lead.product_interest or body[:200]
    elif intent in {"callback_requested", "interested"}:
        lead.status = "contacted"
        lead.qualification_status = "follow_up" if intent == "callback_requested" else "qualified"
        lead.next_action = "follow_up_call"
        lead.next_action_due_at = utc_now() + timedelta(minutes=5)
        lead.last_outreach_at = utc_now()

        from services.outbound_call_service import create_call_task
        existing_task = session.exec(
            select(CallTask).where(
                CallTask.company_id == lead.company_id,
                CallTask.lead_id == lead.id,
                CallTask.status.in_(["pending", "queued", "retry_scheduled", "dialing"]),
                CallTask.dialer_source == "whatsapp_reply",
            ).order_by(CallTask.created_at.desc())
        ).first()
        if existing_task is None:
            created_call_task = create_call_task(
                session=session,
                company_id=lead.company_id,
                actor_user_id=actor_user_id or lead.owner_user_id or 1,
                lead_id=lead.id,
                assigned_user_id=lead.owner_user_id,
                scheduled_at=lead.next_action_due_at,
                notes=f"Auto-created from WhatsApp reply intent: {intent}",
                dialer_source="whatsapp_reply",
                initial_status="queued",
            )

    session.add(lead)
    session.commit()
    session.refresh(lead)
    return {"call_task_id": created_call_task.id if created_call_task else None}


def _progress_campaign_for_whatsapp_reply(
    session: Session,
    company_id: int,
    lead_id: int,
    interaction_id: int,
    actor_user_id: int | None,
    intent: str,
) -> dict[str, Any]:
    from services.campaign_service import get_current_step, schedule_campaign_recipient_next_step
    from services.outcome_service import (
        OUTCOME_NOT_INTERESTED, OUTCOME_INTERESTED,
        OUTCOME_CALLBACK_REQUESTED, OUTCOME_NO_ANSWER,
        ANSWERED_OUTCOMES,
    )

    recipient = _find_active_whatsapp_campaign_recipient(session, company_id, lead_id)
    if not recipient:
        return {"campaign_recipient_id": None, "campaign_status": "not_found"}

    INTENT_TO_OUTCOME = {
        "opt_out":            OUTCOME_NOT_INTERESTED,
        "not_interested":     OUTCOME_NOT_INTERESTED,
        "interested":         OUTCOME_INTERESTED,
        "callback_requested": OUTCOME_CALLBACK_REQUESTED,
        "quote_requested":    OUTCOME_INTERESTED,
        "neutral":            OUTCOME_NO_ANSWER,
    }
    normalized_outcome = INTENT_TO_OUTCOME.get(intent, OUTCOME_NO_ANSWER)

    recipient.last_contact_at = utc_now()
    recipient.last_interaction_id = interaction_id
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id

    if normalized_outcome in {OUTCOME_NOT_INTERESTED}:
        recipient.status = "stopped"
        recipient.next_run_at = None
        session.add(recipient)
        session.commit()
        session.refresh(recipient)
    elif normalized_outcome in ANSWERED_OUTCOMES:
        session.add(recipient)
        session.commit()
        session.refresh(recipient)
        schedule_campaign_recipient_next_step(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id or 0,
            recipient=recipient,
        )
    else:
        recipient.status = "responded"
        session.add(recipient)
        session.commit()
        session.refresh(recipient)

    return {
        "campaign_recipient_id": recipient.id,
        "campaign_status": recipient.status,
        "normalized_outcome": normalized_outcome,
    }


# ── Main webhook entrypoint ───────────────────────────────────────────────────

def ingest_whatsapp_webhook_event(
    session: Session,
    payload: dict[str, Any],
    forced_company_id: int | None = None,
) -> dict[str, Any]:
    provider_message_sid = str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip() or None
    provider_status = str(payload.get("MessageStatus") or payload.get("SmsStatus") or "").strip().lower() or None
    from_number = str(payload.get("From") or "").strip() or None
    to_number   = str(payload.get("To") or "").strip() or None
    body        = str(payload.get("Body") or "").strip()

    # ── Status update for an outbound message ────────────────────────────────
    if provider_message_sid:
        interaction = _get_whatsapp_interaction_by_provider_sid(session, provider_message_sid)
        if interaction:
            metadata = dict(interaction.metadata_json or {})
            metadata.setdefault("provider_events", []).append(dict(payload))
            metadata["provider_message_sid"] = provider_message_sid
            if provider_status:
                metadata["provider_message_status"] = provider_status
            interaction.metadata_json = metadata
            interaction.updated_at = utc_now()

            delivery_status_map = {
                "queued": "pending", "accepted": "sent", "sent": "sent",
                "delivered": "delivered", "read": "read",
                "failed": "failed", "undelivered": "failed",
            }
            if provider_status in delivery_status_map:
                interaction.delivery_status = delivery_status_map[provider_status]
                if provider_status in {"failed", "undelivered"}:
                    interaction.status = "failed"
                elif provider_status in {"sent", "delivered", "read"}:
                    interaction.status = "completed"

            session.add(interaction)
            session.commit()
            record_whatsapp_event(
                session=session,
                company_id=interaction.company_id,
                interaction_id=interaction.id,
                event_type=provider_status or "status_update",
                payload=dict(payload),
            )
            return {
                "status": "status_recorded",
                "interaction_id": interaction.id,
                "company_id": interaction.company_id,
                "provider_message_sid": provider_message_sid,
                "provider_status": provider_status,
            }

    # ── Inbound reply from lead ───────────────────────────────────────────────
    if body and from_number and to_number:
        company_id = forced_company_id or _resolve_company_id_by_whatsapp_number(session, to_number)
        if company_id is None:
            return {"status": "ignored", "reason": "company_not_found"}

        lead = session.exec(
            select(Lead).where(
                Lead.company_id == company_id,
                Lead.normalized_phone == _normalize_channel_phone(from_number),
            )
        ).first()
        if not lead:
            return {"status": "ignored", "reason": "lead_not_found", "company_id": company_id}

        interaction = Interaction(
            company_id=company_id,
            lead_id=lead.id,
            user_id=lead.owner_user_id,
            type="communication",
            channel="whatsapp",
            direction="inbound",
            source="twilio",
            content=body[:200],
            delivery_status="received",
            metadata_json={
                "body": body,
                "provider_message_sid": provider_message_sid,
                "from": from_number,
                "to": to_number,
                "provider_payload": dict(payload),
            },
            status="completed",
            started_at=utc_now(),
            ended_at=utc_now(),
            created_by=lead.owner_user_id,
            updated_by=lead.owner_user_id,
        )
        session.add(interaction)
        session.commit()
        session.refresh(interaction)

        intent = classify_reply_intent(body)
        lead_update_result = _update_lead_for_whatsapp_reply(
            session=session, lead=lead, actor_user_id=lead.owner_user_id, body=body, intent=intent,
        )
        campaign_result = _progress_campaign_for_whatsapp_reply(
            session=session, company_id=company_id, lead_id=lead.id,
            interaction_id=interaction.id, actor_user_id=lead.owner_user_id, intent=intent,
        )

        quote_result: dict[str, Any] = {}
        if intent == "quote_requested":
            from services.next_action_service import handle_inbound_quote_request
            quote_result = handle_inbound_quote_request(
                session=session,
                company_id=company_id,
                actor_user_id=lead.owner_user_id or 1,
                lead_id=lead.id,
                request_text=body,
                preferred_channel="whatsapp",
            )
            interaction = session.get(Interaction, interaction.id)
            if interaction:
                metadata = dict(interaction.metadata_json or {})
                metadata["quote_request_result"] = quote_result
                interaction.metadata_json = metadata
                interaction.updated_at = utc_now()
                session.add(interaction)
                session.commit()

        auto_reply_result = _send_whatsapp_auto_reply(
            session=session, company_id=company_id, lead_id=lead.id,
            actor_user_id=lead.owner_user_id, intent=intent, quote_result=quote_result,
        )
        record_whatsapp_event(
            session=session,
            company_id=company_id,
            interaction_id=interaction.id,
            event_type="reply",
            payload={**dict(payload), "intent": intent},
        )
        return {
            "status": "reply_recorded",
            "interaction_id": interaction.id,
            "company_id": company_id,
            "lead_id": lead.id,
            "intent": intent,
            "auto_reply_sent": auto_reply_result is not None and auto_reply_result.get("success"),
            "call_task_id": lead_update_result["call_task_id"],
            **campaign_result,
            **({k: v for k, v in quote_result.items() if k != "status"}),
            **({"quote_request_status": quote_result["status"]} if quote_result.get("status") else {}),
        }

    return {"status": "ignored", "reason": "unsupported_payload"}

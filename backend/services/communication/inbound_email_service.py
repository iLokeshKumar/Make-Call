"""
Inbound email webhook ingestion — deduplication, lead lookup,
reply-intent classification, lead state updates, engagement recording.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlmodel import Session, select

from models.models import Interaction, Lead, utc_now
from services.leads.engagement_service import record_engagement_event
from services.communication.inbound_whatsapp_service import classify_reply_intent
from services.leads.opt_out_service import unsubscribe_lead



def _normalize_email_address(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower()


def _resolve_company_id_by_email_address(session: Session, to_address: str | None) -> int | None:
    from models.models import CompanySetting
    normalized_to = _normalize_email_address(to_address)
    if not normalized_to:
        return None
    settings = session.exec(
        select(CompanySetting).where(
            CompanySetting.key.in_(["INBOUND_EMAIL_ADDRESS", "INBOUND_EMAIL_ALIAS"])
        )
    ).all()
    for setting in settings:
        if _normalize_email_address(setting.value) == normalized_to:
            return setting.company_id
    return None


def resolve_company_id_by_email_address(session: Session, to_address: str | None) -> int | None:
    return _resolve_company_id_by_email_address(session, to_address)


def _find_lead_by_email(session: Session, company_id: int, email_address: str | None) -> Lead | None:
    normalized = _normalize_email_address(email_address)
    if not normalized:
        return None
    return session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            func.lower(Lead.email) == normalized,
        )
    ).first()


def _get_email_interaction_by_message_id(session: Session, message_id: str | None) -> Interaction | None:
    if not message_id:
        return None
    interactions = session.exec(select(Interaction).where(Interaction.channel == "email")).all()
    for interaction in interactions:
        metadata = interaction.metadata_json or {}
        if metadata.get("message_id") == message_id:
            return interaction
    return None


def _update_lead_for_email_reply(
    session: Session,
    lead: Lead,
    actor_user_id: int | None,
    body: str,
    intent: str,
) -> dict[str, Any]:
    lead.updated_at = utc_now()
    if actor_user_id is not None:
        lead.updated_by = actor_user_id

    if intent == "opt_out":
        unsubscribe_lead(
            session=session,
            company_id=lead.company_id,
            actor_user_id=actor_user_id,
            lead_id=lead.id,
            channel="email",
            reason="Opt out via email reply",
        )
        lead.status = "closed_lost"
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
    elif intent == "callback_requested":
        lead.status = "contacted"
        lead.qualification_status = "follow_up"
        lead.next_action = "follow_up_call"
        lead.next_action_due_at = utc_now()

    session.add(lead)
    session.commit()
    session.refresh(lead)
    return {"call_task_id": None}


# Main webhook entrypoint

def ingest_email_webhook_event(
    session: Session,
    payload: dict[str, Any],
    forced_company_id: int | None = None,
) -> dict[str, Any]:
    message_id = str(payload.get("Message-ID") or payload.get("MessageId") or "").strip() or None
    subject    = str(payload.get("Subject") or payload.get("subject") or "").strip()
    body       = str(
        payload.get("Body") or payload.get("body") or
        payload.get("TextBody") or payload.get("text") or ""
    ).strip()
    from_email   = _normalize_email_address(str(payload.get("From") or "").strip())
    to_email     = str(payload.get("To") or payload.get("Recipient") or "").strip()
    normalized_to = _normalize_email_address(to_email)

    if not from_email or not normalized_to:
        return {"status": "ignored", "reason": "missing_from_or_to"}

    if message_id:
        existing = _get_email_interaction_by_message_id(session, message_id)
        if existing:
            return {
                "status": "ignored",
                "reason": "duplicate_message",
                "interaction_id": existing.id,
                "message_id": message_id,
            }

    company_id = forced_company_id or _resolve_company_id_by_email_address(session, normalized_to)
    if company_id is None:
        return {"status": "ignored", "reason": "company_not_found"}

    lead = _find_lead_by_email(session, company_id, from_email)
    if not lead:
        return {"status": "ignored", "reason": "lead_not_found", "company_id": company_id}

    interaction = Interaction(
        company_id=company_id,
        lead_id=lead.id,
        user_id=lead.owner_user_id,
        type="communication",
        channel="email",
        direction="inbound",
        source="inbound",
        content=(subject or body)[:200],
        delivery_status="received",
        metadata_json={
            "body": body,
            "subject": subject,
            "message_id": message_id,
            "from": from_email,
            "to": normalized_to,
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

    intent = classify_reply_intent(subject or body)
    # LLM-backed classification elevates rule-"neutral" replies into the roadmap
    # 5-intent set {interested, objection, unsubscribe, question, noise}.
    try:
        from agents.reply_classifier import classify_reply_sync as _classify_reply_sync
        classification = _classify_reply_sync(session, company_id, subject or body, "email", lead.id)
    except Exception as _cls_exc:  # noqa: BLE001
        classification = {"intent": "noise", "source": "error", "confidence": 0.0, "error": str(_cls_exc)}

    if classification.get("intent") == "unsubscribe" and intent != "opt_out":
        try:
            unsubscribe_lead(
                session=session,
                company_id=company_id,
                actor_user_id=lead.owner_user_id,
                lead_id=lead.id,
                channel="email",
                reason="llm_reply_classifier",
            )
            intent = "opt_out"
        except Exception:  # noqa: BLE001
            pass

    lead_update_result = _update_lead_for_email_reply(
        session=session, lead=lead, actor_user_id=lead.owner_user_id, body=body, intent=intent,
    )

    quote_result: dict[str, Any] = {}
    if intent == "quote_requested":
        from services.next_action_service import handle_inbound_quote_request
        quote_result = handle_inbound_quote_request(
            session=session,
            company_id=company_id,
            actor_user_id=lead.owner_user_id or 1,
            lead_id=lead.id,
            request_text=subject or body,
            preferred_channel="email",
        )
        interaction = session.get(Interaction, interaction.id)
        if interaction:
            metadata = dict(interaction.metadata_json or {})
            metadata["quote_request_result"] = quote_result
            interaction.metadata_json = metadata
            interaction.updated_at = utc_now()
            session.add(interaction)
            session.commit()

    record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=lead.id,
        interaction_id=interaction.id,
        quote_id=None,
        channel="email",
        event_type="reply",
        payload={"intent": intent, "message_id": message_id or ""},
    )

    response: dict[str, Any] = {
        "status": "reply_recorded",
        "interaction_id": interaction.id,
        "company_id": company_id,
        "lead_id": lead.id,
        "intent": intent,
        "classification": classification,
        "call_task_id": lead_update_result["call_task_id"],
        **({k: v for k, v in quote_result.items() if k != "status"}),
        **({"quote_request_status": quote_result["status"]} if quote_result.get("status") else {}),
    }
    if message_id:
        response["message_id"] = message_id
    return response

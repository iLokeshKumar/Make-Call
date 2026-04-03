from __future__ import annotations

import re
from datetime import timedelta
from secrets import token_urlsafe
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from models.models import CallTask, CampaignRecipient, CompanySetting, EngagementEvent, Interaction, Lead, OptOut, Quote, utc_now
from utils.phone import normalize_phone


TRACKABLE_URL_RE = re.compile(r"https?://[^\s<>\"]+")
OPT_OUT_TERMS = {"stop", "unsubscribe", "remove me", "stop messaging", "stop whatsapp", "do not message"}
NOT_INTERESTED_TERMS = {"not interested", "no thanks", "not now", "not looking", "not required"}
CALLBACK_TERMS = {"call me", "call back", "callback", "ring me", "speak later"}
QUOTE_TERMS = {"quote", "pricing", "price", "proposal", "estimate"}
INTERESTED_TERMS = {"interested", "yes", "sounds good", "tell me more", "share details", "details please"}


def generate_tracking_token() -> str:
    return token_urlsafe(24)


def is_lead_opted_out(session: Session, company_id: int, lead_id: int, channel: str) -> bool:
    existing = session.exec(
        select(OptOut).where(
            OptOut.company_id == company_id,
            OptOut.lead_id == lead_id,
            OptOut.channel == channel,
        )
    ).first()
    return existing is not None


def unsubscribe_lead(
    session: Session,
    company_id: int,
    actor_user_id: int | None,
    lead_id: int,
    channel: str,
    reason: str | None = None,
) -> OptOut:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    existing = session.exec(
        select(OptOut).where(
            OptOut.company_id == company_id,
            OptOut.lead_id == lead_id,
            OptOut.channel == channel,
        )
    ).first()
    if existing:
        return existing

    opt_out = OptOut(
        company_id=company_id,
        lead_id=lead_id,
        channel=channel,
        reason=reason,
    )
    session.add(opt_out)
    lead.updated_at = utc_now()
    if actor_user_id is not None:
        lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()
    session.refresh(opt_out)
    record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=None,
        quote_id=None,
        channel=channel,
        event_type="unsubscribe",
        payload={"reason": reason},
    )
    return opt_out


def record_engagement_event(
    session: Session,
    company_id: int,
    lead_id: int | None,
    interaction_id: int | None,
    quote_id: int | None,
    channel: str | None,
    event_type: str,
    payload: dict | None = None,
) -> EngagementEvent:
    event = EngagementEvent(
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        quote_id=quote_id,
        channel=channel,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def ensure_interaction_tracking_token(session: Session, interaction: Interaction, token_key: str = "tracking_token") -> str:
    metadata = interaction.metadata_json or {}
    token = metadata.get(token_key)
    if not token:
        token = generate_tracking_token()
        metadata[token_key] = token
        interaction.metadata_json = metadata
        session.add(interaction)
        session.commit()
        session.refresh(interaction)
    return token


def build_open_tracking_pixel(tracking_base_url: str, token: str) -> str:
    return (
        f'<img src="{tracking_base_url.rstrip("/")}/tracking/email/open/{token}" '
        'alt="" width="1" height="1" style="display:none;" />'
    )


def build_email_click_tracking_url(tracking_base_url: str, token: str, target_url: str) -> str:
    encoded_target = quote(target_url, safe="")
    return f"{tracking_base_url.rstrip('/')}/tracking/email/click/{token}?target={encoded_target}"


def rewrite_click_tracking_links(body: str, tracking_base_url: str, token: str) -> str:
    if not body or not token:
        return body

    tracking_prefix = f"{tracking_base_url.rstrip('/')}/tracking/email/click/"

    def replace(match: re.Match[str]) -> str:
        url = match.group(0)
        if url.startswith(tracking_prefix):
            return url
        return build_email_click_tracking_url(tracking_base_url, token, url)

    return TRACKABLE_URL_RE.sub(replace, body)


def build_unsubscribe_url(tracking_base_url: str, token: str, channel: str) -> str:
    return (
        f"{tracking_base_url.rstrip('/')}/tracking/unsubscribe"
        f"?token={quote(token, safe='')}&channel={quote(channel, safe='')}"
    )


def build_quote_view_url(tracking_base_url: str, token: str) -> str:
    return f"{tracking_base_url.rstrip('/')}/tracking/quote/view/{token}"


def record_email_sent(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    interaction_id: int,
    tracking_payload: dict | None = None,
) -> dict[str, Any]:
    interaction = session.get(Interaction, interaction_id)
    if not interaction or interaction.company_id != company_id:
        raise HTTPException(status_code=404, detail="Interaction not found")

    metadata = interaction.metadata_json or {}
    metadata.update(tracking_payload or {})
    interaction.metadata_json = metadata
    interaction.delivery_status = "sent"
    interaction.status = "completed"
    interaction.updated_at = utc_now()
    interaction.updated_by = actor_user_id
    session.add(interaction)
    session.commit()

    event = record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        quote_id=None,
        channel="email",
        event_type="sent",
        payload=tracking_payload or {},
    )
    return {"interaction_id": interaction_id, "event_id": event.id}


def _get_interaction_by_token(session: Session, token: str) -> Interaction | None:
    interactions = session.exec(select(Interaction).where(Interaction.channel == "email")).all()
    for interaction in interactions:
        metadata = interaction.metadata_json or {}
        if metadata.get("tracking_token") == token:
            return interaction
    return None


def get_quote_by_tracking_token(session: Session, token: str) -> Quote | None:
    return session.exec(select(Quote).where(Quote.tracking_token == token)).first()


def _get_whatsapp_interaction_by_provider_sid(session: Session, provider_message_sid: str) -> Interaction | None:
    interactions = session.exec(select(Interaction).where(Interaction.channel == "whatsapp")).all()
    for interaction in interactions:
        metadata = interaction.metadata_json or {}
        if metadata.get("provider_message_sid") == provider_message_sid:
            return interaction
    return None


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


def _normalize_email_address(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower()


def _resolve_company_id_by_email_address(session: Session, to_address: str | None) -> int | None:
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

        if lead.normalized_phone and not is_lead_opted_out(session, lead.company_id, lead.id, "call"):
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


def _progress_campaign_for_whatsapp_reply(
    session: Session,
    company_id: int,
    lead_id: int,
    interaction_id: int,
    actor_user_id: int | None,
    intent: str,
) -> dict[str, Any]:
    recipient = _find_active_whatsapp_campaign_recipient(session, company_id, lead_id)
    if not recipient:
        return {"campaign_recipient_id": None, "campaign_status": "not_found"}

    recipient.last_contact_at = utc_now()
    recipient.last_interaction_id = interaction_id
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    recipient.next_run_at = None
    recipient.status = "stopped" if intent in {"opt_out", "not_interested"} else "responded"
    session.add(recipient)
    session.commit()
    session.refresh(recipient)
    return {"campaign_recipient_id": recipient.id, "campaign_status": recipient.status}


def record_email_open(session: Session, token: str) -> dict[str, Any]:
    interaction = _get_interaction_by_token(session, token)
    if not interaction:
        raise HTTPException(status_code=404, detail="Tracking token not found")

    metadata = dict(interaction.metadata_json or {})
    metadata["opened_at"] = utc_now().isoformat()
    interaction.metadata_json = metadata
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()

    event = record_engagement_event(
        session=session,
        company_id=interaction.company_id,
        lead_id=interaction.lead_id,
        interaction_id=interaction.id,
        quote_id=None,
        channel="email",
        event_type="open",
        payload={"tracking_token": token},
    )
    return {"interaction_id": interaction.id, "event_id": event.id}


def record_email_click(session: Session, token: str, target_url: str) -> dict[str, Any]:
    interaction = _get_interaction_by_token(session, token)
    if not interaction:
        raise HTTPException(status_code=404, detail="Tracking token not found")

    event = record_engagement_event(
        session=session,
        company_id=interaction.company_id,
        lead_id=interaction.lead_id,
        interaction_id=interaction.id,
        quote_id=None,
        channel="email",
        event_type="click",
        payload={"tracking_token": token, "target_url": target_url},
    )
    return {"interaction_id": interaction.id, "event_id": event.id, "target_url": target_url}


def record_whatsapp_event(
    session: Session,
    company_id: int,
    interaction_id: int | None,
    event_type: str,
    payload: dict | None,
) -> dict[str, Any]:
    lead_id = None
    if interaction_id is not None:
        interaction = session.get(Interaction, interaction_id)
        if interaction and interaction.company_id == company_id:
            lead_id = interaction.lead_id
            metadata = interaction.metadata_json or {}
            metadata.setdefault("whatsapp_events", []).append({"event_type": event_type, "payload": payload or {}})
            interaction.metadata_json = metadata
            interaction.updated_at = utc_now()
            session.add(interaction)
            session.commit()

    event = record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        quote_id=None,
        channel="whatsapp",
        event_type=event_type,
        payload=payload or {},
    )
    return {"event_id": event.id}


def ingest_whatsapp_webhook_event(
    session: Session,
    payload: dict[str, Any],
    forced_company_id: int | None = None,
) -> dict[str, Any]:
    provider_message_sid = str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip() or None
    provider_status = str(payload.get("MessageStatus") or payload.get("SmsStatus") or "").strip().lower() or None
    from_number = str(payload.get("From") or "").strip() or None
    to_number = str(payload.get("To") or "").strip() or None
    body = str(payload.get("Body") or "").strip()

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
            session=session,
            lead=lead,
            actor_user_id=lead.owner_user_id,
            body=body,
            intent=intent,
        )
        campaign_result = _progress_campaign_for_whatsapp_reply(
            session=session,
            company_id=company_id,
            lead_id=lead.id,
            interaction_id=interaction.id,
            actor_user_id=lead.owner_user_id,
            intent=intent,
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
            "call_task_id": lead_update_result["call_task_id"],
            **campaign_result,
            **({k: v for k, v in quote_result.items() if k != "status"}),
            **({"quote_request_status": quote_result["status"]} if quote_result.get("status") else {}),
        }

    return {"status": "ignored", "reason": "unsupported_payload"}


def ingest_email_webhook_event(
    session: Session,
    payload: dict[str, Any],
    forced_company_id: int | None = None,
) -> dict[str, Any]:
    message_id = str(payload.get("Message-ID") or payload.get("MessageId") or "").strip() or None
    subject = str(payload.get("Subject") or payload.get("subject") or "").strip()
    body = str(
        payload.get("Body")
        or payload.get("body")
        or payload.get("TextBody")
        or payload.get("text")
        or ""
    ).strip()
    from_email = _normalize_email_address(str(payload.get("From") or "").strip())
    to_email = str(payload.get("To") or payload.get("Recipient") or "").strip()
    normalized_to = _normalize_email_address(to_email)

    if not from_email or not normalized_to:
        return {"status": "ignored", "reason": "missing_from_or_to"}

    if message_id:
        existing_interaction = _get_email_interaction_by_message_id(session, message_id)
        if existing_interaction:
            return {
                "status": "ignored",
                "reason": "duplicate_message",
                "interaction_id": existing_interaction.id,
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
    lead_update_result = _update_lead_for_email_reply(
        session=session,
        lead=lead,
        actor_user_id=lead.owner_user_id,
        body=body,
        intent=intent,
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

    response = {
        "status": "reply_recorded",
        "interaction_id": interaction.id,
        "company_id": company_id,
        "lead_id": lead.id,
        "intent": intent,
        "call_task_id": lead_update_result["call_task_id"],
        **({k: v for k, v in quote_result.items() if k != "status"}),
        **({"quote_request_status": quote_result["status"]} if quote_result.get("status") else {}),
    }
    if message_id:
        response["message_id"] = message_id
    return response


def record_quote_event(
    session: Session,
    company_id: int,
    quote_id: int,
    event_type: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    quote = session.exec(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.company_id == company_id,
        )
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    now = utc_now()
    quote_opened_first_time = False
    if event_type == "opened" and quote.opened_at is None:
        quote.opened_at = now
        quote_opened_first_time = True
    elif event_type == "sent" and quote.sent_at is None:
        quote.sent_at = now
    elif event_type == "accepted":
        quote.accepted_at = now
        quote.status = "accepted"
    elif event_type == "rejected":
        quote.rejected_at = now
        quote.status = "rejected"

    session.add(quote)
    session.commit()

    event = record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=quote.lead_id,
        interaction_id=None,
        quote_id=quote.id,
        channel="quote",
        event_type=event_type,
        payload=payload or {},
    )
    
    # Trigger follow-up automation when quote is opened
    if quote_opened_first_time:
        lead = session.get(Lead, quote.lead_id)
        if lead:
            lead.next_action = "quote_opened"
            lead.next_action_due_at = now
            lead.updated_at = now
            session.add(lead)
            session.commit()
    
    return {"quote_id": quote.id, "event_id": event.id, "automation_triggered": quote_opened_first_time}


def record_quote_open_by_token(session: Session, token: str) -> dict[str, Any]:
    quote = get_quote_by_tracking_token(session, token)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote tracking token not found")
    return record_quote_event(
        session=session,
        company_id=quote.company_id,
        quote_id=quote.id,
        event_type="opened",
        payload={"tracking_token": token},
    )


def get_public_quote_info(session: Session, token: str) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=400, detail="Missing quote token")

    quote = get_quote_by_tracking_token(session, token)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    lead = session.get(Lead, quote.lead_id)
    events = session.exec(
        select(EngagementEvent)
        .where(EngagementEvent.quote_id == quote.id)
        .order_by(EngagementEvent.created_at.asc())
    ).all()

    timeline = []
    if quote.created_at:
        timeline.append({"label": "Quote created", "timestamp": quote.created_at.isoformat()})
    if quote.sent_at:
        timeline.append({"label": "Quote sent", "timestamp": quote.sent_at.isoformat()})
    if quote.opened_at:
        timeline.append({"label": "Quote opened", "timestamp": quote.opened_at.isoformat()})
    if quote.accepted_at:
        timeline.append({"label": "Quote accepted", "timestamp": quote.accepted_at.isoformat()})
    if quote.rejected_at:
        timeline.append({"label": "Quote rejected", "timestamp": quote.rejected_at.isoformat()})

    return {
        "quote": {
            "id": quote.id,
            "quote_number": quote.quote_number,
            "status": quote.status,
            "currency": quote.currency,
            "total_amount": str(quote.total_amount),
            "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
            "tracking_token": quote.tracking_token,
            "notes": quote.notes,
            "lead_name": lead.name if lead else None,
            "lead_email": lead.email if lead else None,
            "lead_phone": lead.normalized_phone if lead else None,
        },
        "events": [
            {
                "event_type": event.event_type,
                "channel": event.channel,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
        "timeline": timeline,
    }


def detect_quote_intent(text: str | None) -> bool:
    """
    Detect if interaction text indicates a quote request intent.
    Returns True if quote-related keywords are found.
    """
    if not text:
        return False
    
    text_lower = text.lower().strip()
    for term in QUOTE_TERMS:
        if term in text_lower:
            return True
    return False


def should_trigger_quote_automation(
    session: Session,
    company_id: int,
    lead_id: int,
    intent: str,
    channel: str,
) -> bool:
    """
    Determine if quote automation should be triggered.
    - Only trigger on quote_requested intent
    - Only trigger on email/whatsapp channels
    - Don't trigger if lead is opted out
    """
    if intent != "quote_requested":
        return False
    
    if channel not in ("email", "whatsapp"):
        return False
    
    if is_lead_opted_out(session, company_id, lead_id, channel):
        return False
    
    return True


def detect_and_process_quote_automation(
    session: Session,
    company_id: int,
    lead_id: int,
    interaction_id: int,
    text: str | None,
    channel: str,
) -> dict[str, Any]:
    """
    Detect quote intent from interaction text and trigger automation.
    
    Returns:
    {
        "intent_detected": bool,
        "automation_triggered": bool,
        "quote_id": int | None,
        "call_task_id": int | None,
        "action": "auto_quote_sent" | "follow_up_task_created" | None
    }
    """
    quote_intent_detected = detect_quote_intent(text)
    
    if not quote_intent_detected:
        return {
            "intent_detected": False,
            "automation_triggered": False,
            "quote_id": None,
            "call_task_id": None,
            "action": None,
        }
    
    should_trigger = should_trigger_quote_automation(session, company_id, lead_id, "quote_requested", channel)
    
    if not should_trigger:
        return {
            "intent_detected": True,
            "automation_triggered": False,
            "quote_id": None,
            "call_task_id": None,
            "action": None,
        }
    
    # Import here to avoid circular dependency
    from services.quote_service import auto_create_quote_from_interaction
    
    result = auto_create_quote_from_interaction(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        request_text=text,
        channel=channel,
    )
    
    return result

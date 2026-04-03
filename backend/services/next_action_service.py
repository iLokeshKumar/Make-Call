import logging
import re
from datetime import timedelta

from sqlmodel import Session, select

from models.models import Appointment, CallTask, Lead, LeadRequirement, Product, Quote, QuoteItemCreate, QuoteCreate, utc_now
from services.communication_service import get_company_setting_value, send_quote_to_lead, send_email_to_lead
from services.message_render_service import render_template_by_id
from services.outbound_call_service import create_call_task
from services.requirement_service import get_latest_requirements
from services.tracking_service import is_lead_opted_out

logger = logging.getLogger(__name__)


def _build_quote_delivery_channels(session: Session, company_id: int, lead: Lead, preferred_channel: str | None) -> list[str]:
    channels: list[str] = []
    if lead.email and not is_lead_opted_out(session, company_id, lead.id, "email"):
        channels.append("email")

    whatsapp_allowed = (
        bool(lead.normalized_phone)
        and not is_lead_opted_out(session, company_id, lead.id, "whatsapp")
    )
    if preferred_channel == "whatsapp" and whatsapp_allowed:
        channels.append("whatsapp")
    elif not channels and whatsapp_allowed:
        channels.append("whatsapp")

    return channels


def _extract_candidate_terms(candidate_texts: list[str | None]) -> list[str]:
    terms: list[str] = []
    for text in candidate_texts:
        if not text:
            continue
        for part in re.split(r"[,\n;]+", text):
            cleaned = part.strip()
            if cleaned:
                terms.append(cleaned)
    return terms


def _score_product_match(product: Product, candidate: str) -> int:
    candidate_lower = candidate.strip().lower()
    if not candidate_lower:
        return 0
    name = (product.name or "").lower()
    sku = (product.sku or "").lower()
    score = 0
    if sku and candidate_lower == sku:
        score += 100
    if candidate_lower == name:
        score += 90
    if sku and sku in candidate_lower:
        score += 40
    if name and name in candidate_lower:
        score += 50
    if name and candidate_lower in name:
        score += 30
    for token in re.split(r"[\s\-]+", candidate_lower):
        if token and name and token in name:
            score += 5
    return score


def _resolve_quote_product_match(session: Session, company_id: int, lead: Lead, request_text: str | None) -> Product | None:
    latest_requirement = get_latest_requirements(session, company_id, lead.id)
    candidate_texts = [
        (latest_requirement.required_products if latest_requirement else None),
        lead.product_interest,
        request_text,
    ]
    candidate_terms = _extract_candidate_terms(candidate_texts)
    if not candidate_terms:
        return None

    products = session.exec(
        select(Product).where(
            Product.company_id == company_id,
            Product.is_active == True,
        )
    ).all()
    if not products:
        return None

    scores: dict[int, int] = {}
    product_lookup: dict[int, Product] = {}
    for product in products:
        product_lookup[product.id] = product
        for candidate in candidate_terms:
            score = _score_product_match(product, candidate)
            if score:
                scores[product.id] = max(score, scores.get(product.id, 0))
    if not scores:
        return None

    sorted_matches = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_score = sorted_matches[0][1]
    if top_score < 50:
        return None
    if len(sorted_matches) > 1 and sorted_matches[1][1] == top_score:
        return None
    return product_lookup.get(sorted_matches[0][0])


def _get_open_quote_review_task(session: Session, company_id: int, lead_id: int) -> CallTask | None:
    return session.exec(
        select(CallTask).where(
            CallTask.company_id == company_id,
            CallTask.lead_id == lead_id,
            CallTask.dialer_source == "quote_request_review",
            CallTask.status.in_(["pending", "queued", "retry_scheduled", "dialing"]),
        ).order_by(CallTask.created_at.desc())
    ).first()


def handle_inbound_quote_request(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    request_text: str | None = None,
    preferred_channel: str | None = None,
) -> dict:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return {"status": "skipped", "reason": "lead_not_found"}

    product = _resolve_quote_product_match(session, company_id, lead, request_text)
    if product is None:
        existing_task = _get_open_quote_review_task(session, company_id, lead.id)
        if existing_task:
            lead.next_action = "send_quote"
            lead.next_action_due_at = utc_now()
            lead.updated_at = utc_now()
            lead.updated_by = actor_user_id
            session.add(lead)
            session.commit()
            return {
                "status": "queued_for_review",
                "reason": "insufficient_product_context",
                "call_task_id": existing_task.id,
            }

        if lead.normalized_phone and not is_lead_opted_out(session, company_id, lead.id, "call"):
            review_task = create_call_task(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                assigned_user_id=lead.owner_user_id,
                scheduled_at=utc_now(),
                notes=(
                    "Review inbound quote request. "
                    f"Insufficient product context from reply: {(request_text or '').strip()[:200]}"
                ),
                dialer_source="quote_request_review",
                initial_status="queued",
            )
            lead.next_action = "send_quote"
            lead.next_action_due_at = utc_now()
            lead.updated_at = utc_now()
            lead.updated_by = actor_user_id
            session.add(lead)
            session.commit()
            return {
                "status": "queued_for_review",
                "reason": "insufficient_product_context",
                "call_task_id": review_task.id,
            }

        lead.next_action = "send_quote"
        lead.next_action_due_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        return {
            "status": "queued_for_review",
            "reason": "insufficient_product_context_no_callable_phone",
            "call_task_id": None,
        }

    channels = _build_quote_delivery_channels(session, company_id, lead, preferred_channel)
    if not channels:
        return {
            "status": "queued_for_review",
            "reason": "no_delivery_channel",
            "call_task_id": None,
        }

    from services.quote_service import create_quote, generate_quote_pdf

    quote = create_quote(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        data=QuoteCreate(
            lead_id=lead.id,
            account_id=lead.account_id,
            currency=product.currency or "INR",
            notes="Auto-created from inbound quote request",
            items=[
                QuoteItemCreate(
                    product_id=product.id,
                    product_name_snapshot=product.name,
                    quantity=1,
                    unit_price=product.price,
                )
            ],
        ),
    )
    quote = generate_quote_pdf(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        quote_id=quote.id,
    )
    send_result = send_quote_to_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        quote_id=quote.id,
        channels=channels,
        subject=f"Quotation {quote.quote_number}",
        message=f"Your quotation for {product.name} is ready. Total: {quote.currency} {quote.total_amount}",
    )

    lead.status = "contacted"
    lead.qualification_status = "qualified"
    lead.next_action = "await_quote_response"
    lead.next_action_due_at = utc_now() + timedelta(days=2)
    lead.last_outreach_at = utc_now()
    lead.updated_at = utc_now()
    lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()

    return {
        "status": "created_and_sent",
        "quote_id": quote.id,
        "quote_number": quote.quote_number,
        "product_id": product.id,
        "channels": channels,
        "send_result": send_result,
    }


def dispatch_next_action(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    requirement: LeadRequirement,
):
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        logger.warning(f"Lead {lead_id} not found for next-action dispatch")
        return {"status": "skipped", "reason": "lead_not_found"}

    structured = requirement.structured_data or {}
    next_action = structured.get("next_action") or lead.next_action or "none"
    qualification_status = structured.get("qualification_status") or lead.qualification_status

    if qualification_status:
        lead.qualification_status = qualification_status

    lead.next_action = next_action
    lead.updated_at = utc_now()
    lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()

    if next_action == "send_quote":
        required_products = requirement.required_products or structured.get("required_products")
        if not required_products:
            return {"status": "skipped", "reason": "no_required_products"}

        quote = create_quote(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            data=QuoteCreate(
                lead_id=lead.id,
                account_id=lead.account_id,
                currency="INR",
                notes="Auto-created from ISM next action",
                items=[
                    QuoteItemCreate(
                        product_id=None,
                        product_name_snapshot=required_products,
                        quantity=1,
                    )
                ],
            ),
        )

        quote = generate_quote_pdf(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            quote_id=quote.id,
        )

        quote_email_template_id = get_company_setting_value(session, company_id, "QUOTE_EMAIL_TEMPLATE_ID")
        quote_whatsapp_template_id = get_company_setting_value(session, company_id, "QUOTE_WHATSAPP_TEMPLATE_ID")

        subject = None
        message = None
        channels = []

        if lead.email:
            channels.append("email")
            if quote_email_template_id:
                try:
                    rendered = render_template_by_id(
                        session=session,
                        company_id=company_id,
                        template_id=int(quote_email_template_id),
                        lead_id=lead.id,
                        quote_id=quote.id,
                    )
                    subject = rendered["subject"] or f"Quotation {quote.quote_number}"
                    message = rendered["body"]
                except Exception as e:
                    logger.warning(f"Quote email template render failed: {e}")

        if lead.normalized_phone:
            channels.append("whatsapp")
            if not message and quote_whatsapp_template_id:
                try:
                    rendered = render_template_by_id(
                        session=session,
                        company_id=company_id,
                        template_id=int(quote_whatsapp_template_id),
                        lead_id=lead.id,
                        quote_id=quote.id,
                    )
                    if not subject:
                        subject = rendered["subject"] or f"Quotation {quote.quote_number}"
                    message = rendered["body"]
                except Exception as e:
                    logger.warning(f"Quote WhatsApp template render failed: {e}")

        if not message:
            subject = subject or f"Quotation {quote.quote_number}"
            message = f"Your quotation {quote.quote_number} is ready. Total: {quote.currency} {quote.total_amount}"

        send_result = send_quote_to_lead(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            quote_id=quote.id,
            channels=channels or ["email"],
            subject=subject,
            message=message,
        )

        return {
            "status": "created_and_sent",
            "action": "send_quote",
            "quote_id": quote.id,
            "quote_number": quote.quote_number,
            "send_result": send_result,
        }

    if next_action == "follow_up_call":
        task = create_call_task(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead.id,
            scheduled_at=utc_now() + timedelta(days=1),
            notes="Auto-created from ISM next action: follow_up_call",
        )
        return {
            "status": "created",
            "action": "follow_up_call",
            "call_task_id": task.id,
        }

    if next_action == "follow_up_email":
        if not lead.email:
            return {"status": "skipped", "reason": "lead_has_no_email"}

        template_id = get_company_setting_value(session, company_id, "FOLLOW_UP_EMAIL_TEMPLATE_ID")
        subject = f"Following up from Rio CRM"
        body = "Thank you for your time. I’m following up based on our recent conversation."

        if template_id:
            try:
                rendered = render_template_by_id(
                    session=session,
                    company_id=company_id,
                    template_id=int(template_id),
                    lead_id=lead.id,
                )
                subject = rendered["subject"] or subject
                body = rendered["body"]
            except Exception as e:
                logger.warning(f"Follow-up template render failed: {e}")

        result = send_email_to_lead(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead.id,
            subject=subject,
            body=body,
        )
        return {
            "status": "sent",
            "action": "follow_up_email",
            "result": result,
        }

    if next_action == "schedule_demo":
        appointment = Appointment(
            company_id=company_id,
            lead_id=lead.id,
            owner_user_id=lead.owner_user_id,
            appointment_time=utc_now() + timedelta(days=2),
            status="scheduled",
            notes="Auto-created from ISM next action: schedule_demo",
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        session.add(appointment)
        session.commit()
        session.refresh(appointment)

        return {
            "status": "created",
            "action": "schedule_demo",
            "appointment_id": appointment.id,
        }

    if next_action == "close_lost":
        lead.status = "closed_lost"
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()

        return {
            "status": "updated",
            "action": "close_lost",
        }

    return {
        "status": "no_action",
        "action": next_action,
    }

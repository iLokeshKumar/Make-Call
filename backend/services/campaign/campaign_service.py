import logging
from datetime import datetime, timedelta, timezone
from typing import Iterable

logger = logging.getLogger(__name__)

from fastapi import HTTPException
from sqlalchemy import or_
from sqlmodel import Session, select

from models.models import (
    Campaign,
    CampaignCreate,
    CampaignRecipient,
    CampaignStep,
    CampaignStepCreate,
    CampaignStepUpdate,
    CampaignStepsReorder,
    Lead,
    User,
    utc_now,
    CallTask,
)

from services.call.outbound_call_service import create_call_task

from services.communication.communication_service import send_email_to_lead, send_whatsapp_to_lead
from services.message_render_service import render_template_by_id
from services.call.outcome_service import ANSWERED_OUTCOMES, normalize_call_outcome

def create_campaign(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: CampaignCreate,
) -> Campaign:
    campaign = Campaign(
        company_id=company_id,
        name=data.name.strip(),
        channel=data.channel.strip().lower(),
        objective=data.objective.strip().lower(),
        description=data.description,
        target_audience_rule=data.target_audience_rule,
        status="draft",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(campaign)
    session.commit()
    session.refresh(campaign)
    return campaign


def get_campaign_or_404(
    session: Session,
    company_id: int,
    campaign_id: int,
) -> Campaign:
    campaign = session.exec(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.company_id == company_id,
        )
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


def add_campaign_step(
    session: Session,
    company_id: int,
    campaign_id: int,
    actor_user_id: int,
    data: CampaignStepCreate,
) -> CampaignStep:
    campaign = get_campaign_or_404(session, company_id, campaign_id)

    existing = session.exec(
        select(CampaignStep).where(
            CampaignStep.campaign_id == campaign.id,
            CampaignStep.step_order == data.step_order,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Step order already exists")

    step = CampaignStep(
        campaign_id=campaign.id,
        company_id=company_id,
        step_order=data.step_order,
        channel=data.channel.strip().lower(),
        template_id=data.template_id,
        delay_hours=data.delay_hours,
        objective=data.objective,
        is_active=True,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(step)
    session.commit()
    session.refresh(step)
    return step


def list_campaign_steps(
    session: Session,
    company_id: int,
    campaign_id: int,
) -> list[CampaignStep]:
    get_campaign_or_404(session, company_id, campaign_id)
    return session.exec(
        select(CampaignStep).where(
            CampaignStep.company_id == company_id,
            CampaignStep.campaign_id == campaign_id,
        ).order_by(CampaignStep.step_order.asc())
    ).all()


def delete_campaign_step(
    session: Session,
    company_id: int,
    campaign_id: int,
    step_id: int,
) -> None:
    get_campaign_or_404(session, company_id, campaign_id)
    step = session.exec(
        select(CampaignStep).where(
            CampaignStep.id == step_id,
            CampaignStep.campaign_id == campaign_id,
            CampaignStep.company_id == company_id,
        )
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Campaign step not found")
    session.delete(step)
    session.commit()
    # Renumber remaining steps to keep step_order contiguous (1-based)
    remaining = session.exec(
        select(CampaignStep).where(
            CampaignStep.campaign_id == campaign_id,
            CampaignStep.company_id == company_id,
        ).order_by(CampaignStep.step_order.asc())
    ).all()
    for i, s in enumerate(remaining, start=1):
        s.step_order = i
        session.add(s)
    session.commit()


def update_campaign_step(
    session: Session,
    company_id: int,
    campaign_id: int,
    step_id: int,
    actor_user_id: int,
    data: CampaignStepUpdate,
) -> CampaignStep:
    get_campaign_or_404(session, company_id, campaign_id)
    step = session.exec(
        select(CampaignStep).where(
            CampaignStep.id == step_id,
            CampaignStep.campaign_id == campaign_id,
            CampaignStep.company_id == company_id,
        )
    ).first()
    if not step:
        raise HTTPException(status_code=404, detail="Campaign step not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(step, field, value)
    step.updated_by = actor_user_id
    session.add(step)
    session.commit()
    session.refresh(step)
    return step


def reorder_campaign_steps(
    session: Session,
    company_id: int,
    campaign_id: int,
    actor_user_id: int,
    data: CampaignStepsReorder,
) -> list[CampaignStep]:
    """Assign step_order 1, 2, 3... based on the caller-supplied step_ids order.

    Uses a two-pass update to avoid violating the UniqueConstraint(campaign_id, step_order):
      Pass 1 — move all steps to temporary high values (10000 + i)
      Pass 2 — assign final 1-based positions
    """
    get_campaign_or_404(session, company_id, campaign_id)
    steps_by_id = {
        s.id: s
        for s in session.exec(
            select(CampaignStep).where(
                CampaignStep.campaign_id == campaign_id,
                CampaignStep.company_id == company_id,
            )
        ).all()
    }
    # temp values
    for i, step_id in enumerate(data.step_ids):
        if step_id in steps_by_id:
            steps_by_id[step_id].step_order = 10000 + i
            session.add(steps_by_id[step_id])
    session.commit()
    # final 1-based values
    for i, step_id in enumerate(data.step_ids, start=1):
        if step_id in steps_by_id:
            steps_by_id[step_id].step_order = i
            steps_by_id[step_id].updated_by = actor_user_id
            session.add(steps_by_id[step_id])
    session.commit()
    return list_campaign_steps(session, company_id, campaign_id)


def enroll_leads(
    session: Session,
    company_id: int,
    campaign_id: int,
    actor_user_id: int,
    lead_ids: Iterable[int],
) -> dict:
    campaign = get_campaign_or_404(session, company_id, campaign_id)
    lead_ids_list = list(lead_ids)

    if not lead_ids_list:
        return {"added": 0, "skipped": 0}

    # Batch fetch valid leads (2 queries total instead of 2*N)
    valid_leads = session.exec(
        select(Lead).where(
            Lead.id.in_(lead_ids_list),
            Lead.company_id == company_id,
        )
    ).all()
    valid_lead_ids = {lead.id for lead in valid_leads}

    # Batch fetch already-enrolled leads
    existing_lead_ids = set(
        session.exec(
            select(CampaignRecipient.lead_id).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.lead_id.in_(valid_lead_ids),
            )
        ).all()
    )

    new_lead_ids = valid_lead_ids - existing_lead_ids
    skipped = len(lead_ids_list) - len(new_lead_ids)

    for lead_id in new_lead_ids:
        session.add(CampaignRecipient(
            campaign_id=campaign.id,
            company_id=company_id,
            lead_id=lead_id,
            status="pending",
            current_step=1,
            next_run_at=None,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        ))

    session.commit()
    return {"added": len(new_lead_ids), "skipped": skipped}


def launch_campaign(
    session: Session,
    company_id: int,
    campaign_id: int,
    actor_user_id: int,
) -> Campaign:
    campaign = get_campaign_or_404(session, company_id, campaign_id)

    steps = session.exec(
        select(CampaignStep).where(
            CampaignStep.company_id == company_id,
            CampaignStep.campaign_id == campaign.id,
            CampaignStep.is_active == True,
        )
    ).all()
    if not steps:
        raise HTTPException(status_code=400, detail="Campaign has no active steps")

    recipients = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.company_id == company_id,
            CampaignRecipient.campaign_id == campaign.id,
        )
    ).all()
    if not recipients:
        raise HTTPException(status_code=400, detail="Campaign has no recipients")

    now = utc_now()
    for recipient in recipients:
        if recipient.status == "pending":
            recipient.status = "active"
            recipient.next_run_at = now
            recipient.updated_at = now
            recipient.updated_by = actor_user_id
            session.add(recipient)

    campaign.status = "active"
    campaign.start_at = campaign.start_at or now
    campaign.updated_at = now
    campaign.updated_by = actor_user_id
    session.add(campaign)

    session.commit()
    session.refresh(campaign)

    logger.info("campaign launched", extra={
        "event": "campaign_launched",
        "campaign_id": campaign_id,
        "company_id": company_id,
        "recipient_count": len(recipients),
        "step_count": len(steps),
        "actor_user_id": actor_user_id,
    })
    return campaign


def pause_campaign(
    session: Session,
    company_id: int,
    campaign_id: int,
    actor_user_id: int,
) -> Campaign:
    campaign = get_campaign_or_404(session, company_id, campaign_id)
    campaign.status = "paused"
    campaign.updated_at = utc_now()
    campaign.updated_by = actor_user_id
    session.add(campaign)
    session.commit()
    session.refresh(campaign)

    logger.info("campaign paused", extra={
        "event": "campaign_paused",
        "campaign_id": campaign_id,
        "company_id": company_id,
        "actor_user_id": actor_user_id,
    })
    return campaign


def list_campaigns(
    session: Session,
    company_id: int,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    base = select(Campaign).where(Campaign.company_id == company_id)
    total = len(session.exec(base).all())
    items = session.exec(
        base.order_by(Campaign.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def list_campaign_recipients(
    session: Session,
    company_id: int,
    campaign_id: int,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    get_campaign_or_404(session, company_id, campaign_id)
    base = select(CampaignRecipient).where(
        CampaignRecipient.company_id == company_id,
        CampaignRecipient.campaign_id == campaign_id,
    )
    total = len(session.exec(base).all())
    items = session.exec(
        base.order_by(CampaignRecipient.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return {"items": items, "total": total, "limit": limit, "offset": offset}

def get_current_step(
    session: Session,
    company_id: int,
    campaign_id: int,
    step_order: int,
) -> CampaignStep | None:
    return session.exec(
        select(CampaignStep).where(
            CampaignStep.company_id == company_id,
            CampaignStep.campaign_id == campaign_id,
            CampaignStep.step_order == step_order,
            CampaignStep.is_active == True,
        )
    ).first()


def get_next_step(
    session: Session,
    company_id: int,
    campaign_id: int,
    current_step: int,
) -> CampaignStep | None:
    return session.exec(
        select(CampaignStep).where(
            CampaignStep.company_id == company_id,
            CampaignStep.campaign_id == campaign_id,
            CampaignStep.step_order > current_step,
            CampaignStep.is_active == True,
        ).order_by(CampaignStep.step_order.asc())
    ).first()


def schedule_campaign_recipient_now(
    session: Session,
    recipient: CampaignRecipient,
    actor_user_id: int,
) -> CampaignRecipient:
    recipient.status = "active"
    recipient.next_run_at = utc_now()
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    session.add(recipient)
    session.commit()
    session.refresh(recipient)
    return recipient


def schedule_campaign_recipient_next_step(
    session: Session,
    company_id: int,
    actor_user_id: int,
    recipient: CampaignRecipient,
) -> CampaignRecipient:
    next_step = get_next_step(
        session,
        company_id,
        recipient.campaign_id,
        recipient.current_step,
    )

    if not next_step:
        recipient.status = "completed"
        recipient.next_run_at = None
        recipient.processing_started_at = None  # release claim-lock
        recipient.updated_at = utc_now()
        recipient.updated_by = actor_user_id
        session.add(recipient)
        session.commit()
        session.refresh(recipient)
        return recipient

    recipient.current_step = next_step.step_order
    recipient.next_run_at = utc_now() + timedelta(hours=next_step.delay_hours)
    recipient.status = "active"
    recipient.processing_started_at = None  # release claim-lock
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    session.add(recipient)
    session.commit()
    session.refresh(recipient)
    return recipient


def process_campaign_call_step(
    session: Session,
    company_id: int,
    actor_user_id: int,
    recipient_id: int,
    assigned_user_id: int | None = None,
    campaign_recipient_id: int | None = None,
) -> dict:
    recipient = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.id == recipient_id,
            CampaignRecipient.company_id == company_id,
        )
    ).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Campaign recipient not found")

    step = get_current_step(
        session,
        company_id,
        recipient.campaign_id,
        recipient.current_step,
    )
    if not step:
        raise HTTPException(status_code=404, detail="Campaign step not found")

    if step.channel != "call":
        raise HTTPException(status_code=400, detail="Current campaign step is not a call step")

    call_task = create_call_task(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=recipient.lead_id,
        campaign_id=recipient.campaign_id,
        campaign_step_id=step.id,
        assigned_user_id=assigned_user_id,
        campaign_recipient_id=campaign_recipient_id or recipient.id,
        scheduled_at=utc_now(),
        notes=f"Generated from campaign {recipient.campaign_id}, step {step.step_order}",
    )

    recipient.last_contact_at = utc_now()
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    session.add(recipient)
    session.commit()
    session.refresh(recipient)

    return {
        "recipient_id": recipient.id,
        "campaign_id": recipient.campaign_id,
        "step_order": recipient.current_step,
        "call_task_id": call_task.id,
        "status": "call_task_created",
    }


def mark_campaign_recipient_contacted(
    session: Session,
    company_id: int,
    actor_user_id: int,
    recipient_id: int,
    interaction_id: int | None = None,
) -> CampaignRecipient:
    recipient = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.id == recipient_id,
            CampaignRecipient.company_id == company_id,
        )
    ).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Campaign recipient not found")

    recipient.last_contact_at = utc_now()
    if interaction_id is not None:
        recipient.last_interaction_id = interaction_id
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    session.add(recipient)
    session.commit()
    session.refresh(recipient)
    return recipient


def pause_campaign_recipient(
    session: Session,
    company_id: int,
    actor_user_id: int,
    recipient_id: int,
) -> CampaignRecipient:
    recipient = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.id == recipient_id,
            CampaignRecipient.company_id == company_id,
        )
    ).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Campaign recipient not found")

    recipient.status = "paused"
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    session.add(recipient)
    session.commit()
    session.refresh(recipient)
    return recipient


def retry_campaign_recipient(
    session: Session,
    company_id: int,
    actor_user_id: int,
    recipient_id: int,
) -> CampaignRecipient:
    recipient = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.id == recipient_id,
            CampaignRecipient.company_id == company_id,
        )
    ).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Campaign recipient not found")

    recipient.status = "active"
    recipient.next_run_at = utc_now()
    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    session.add(recipient)
    session.commit()
    session.refresh(recipient)
    return recipient


def get_due_campaign_recipients(
    session: Session,
    company_id: int | None = None,
) -> list[CampaignRecipient]:
    now = utc_now()
    # Rows where processing_started_at is within the last 10 minutes are currently being processed (or were being processed when the worker crashed). Skip them to prevent double-send. They become eligible again once the lock expires, at which point the step will be re-tried.
    stale_threshold = now - timedelta(minutes=10)
    query = select(CampaignRecipient).where(
        CampaignRecipient.status == "active",
        CampaignRecipient.next_run_at != None,
        CampaignRecipient.next_run_at <= now,
        or_(
            CampaignRecipient.processing_started_at.is_(None),
            CampaignRecipient.processing_started_at < stale_threshold,
        ),
    )

    if company_id is not None:
        query = query.where(CampaignRecipient.company_id == company_id)

    return session.exec(
        query.order_by(CampaignRecipient.next_run_at.asc())
    ).all()

def execute_campaign_recipient_step(
    session: Session,
    recipient: CampaignRecipient,
    actor_user_id: int,
) -> dict:
    # Claim the recipient before any I/O so a worker crash between here and the final commit doesn't cause another cycle to re-send immediately. get_due_campaign_recipients skips rows where processing_started_at is within the last 10 minutes, so this is the double-send guard.
    recipient.processing_started_at = utc_now()
    recipient.updated_at = utc_now()
    session.add(recipient)
    session.commit()

    step = get_current_step(
        session=session,
        company_id=recipient.company_id,
        campaign_id=recipient.campaign_id,
        step_order=recipient.current_step,
    )
    if not step:
        raise HTTPException(status_code=404, detail="Current campaign step not found")

    lead = session.exec(
        select(Lead).where(
            Lead.id == recipient.lead_id,
            Lead.company_id == recipient.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if step.channel == "call":
        return process_campaign_call_step(
            session=session,
            company_id=recipient.company_id,
            actor_user_id=actor_user_id,
            recipient_id=recipient.id,
            assigned_user_id=lead.owner_user_id,
            campaign_recipient_id=recipient.id,
        )

    if not step.template_id:
        raise HTTPException(status_code=400, detail="Non-call campaign step requires template_id")

    rendered = render_template_by_id(
        session=session,
        company_id=recipient.company_id,
        template_id=step.template_id,
        lead_id=lead.id,
    )

    if step.channel == "email":
        result = send_email_to_lead(
            session=session,
            company_id=recipient.company_id,
            actor_user_id=actor_user_id,
            lead_id=lead.id,
            subject=rendered["subject"] or "Message from Sales",
            body=rendered["body"],
        )
        recipient.last_contact_at = utc_now()
        recipient.updated_at = utc_now()
        recipient.updated_by = actor_user_id
        session.add(recipient)
        session.commit()

        return {
            "recipient_id": recipient.id,
            "campaign_id": recipient.campaign_id,
            "step_order": recipient.current_step,
            "channel": "email",
            "result": result,
        }

    if step.channel == "whatsapp":
        result = send_whatsapp_to_lead(
            session=session,
            company_id=recipient.company_id,
            actor_user_id=actor_user_id,
            lead_id=lead.id,
            body=rendered["body"],
        )
        recipient.last_contact_at = utc_now()
        recipient.updated_at = utc_now()
        recipient.updated_by = actor_user_id
        session.add(recipient)
        session.commit()

        return {
            "recipient_id": recipient.id,
            "campaign_id": recipient.campaign_id,
            "step_order": recipient.current_step,
            "channel": "whatsapp",
            "result": result,
        }

    raise HTTPException(status_code=400, detail=f"Unsupported campaign channel: {step.channel}")

def run_due_campaign_recipients(
    session: Session,
    actor_user_id: int,
    company_id: int | None = None,
) -> list[dict]:
    recipients = get_due_campaign_recipients(session, company_id=company_id)
    results = []

    for recipient in recipients:
        try:
            result = execute_campaign_recipient_step(
                session=session,
                recipient=recipient,
                actor_user_id=actor_user_id,
            )

            # Auto-advance only for email/whatsapp.
            # For call, advance later after call outcome is processed.
            # if result.get("channel") in {"email", "whatsapp"}:
            #     updated_recipient = session.exec(
            #         select(CampaignRecipient).where(
            #             CampaignRecipient.id == recipient.id,
            #             CampaignRecipient.company_id == recipient.company_id,
            #         )
            #     ).first()
            #     if updated_recipient:
            #         schedule_campaign_recipient_next_step(
            #             session=session,
            #             company_id=recipient.company_id,
            #             actor_user_id=actor_user_id,
            #             recipient=updated_recipient,
            #         )

            # results.append({"success": True, "data": result})



            channel = result.get("channel")
            step_status = result.get("status")

            # For call steps: outcome_service.apply_call_outcome() drives advancement
            # For email/whatsapp: treat a sent result as a normalized "answered" outcome to advance the step — do NOT advance on call_task_created (that waits for the real callback)
            if channel in {"email", "whatsapp"} and step_status != "call_task_created":
                updated_recipient = session.exec(
                    select(CampaignRecipient).where(
                        CampaignRecipient.id == recipient.id,
                        CampaignRecipient.company_id == recipient.company_id,
                    )
                ).first()
                if updated_recipient:
                    schedule_campaign_recipient_next_step(
                        session=session,
                        company_id=recipient.company_id,
                        actor_user_id=actor_user_id,
                        recipient=updated_recipient,
                    )
            # For call steps: advancement happens inside outcome_service._update_campaign_recipient_for_outcome() when the Twilio status callback fires — nothing to do here.

            logger.info("campaign step executed", extra={
                "event": "campaign_step_executed",
                "recipient_id": recipient.id,
                "campaign_id": recipient.campaign_id,
                "company_id": recipient.company_id,
                "step_order": recipient.current_step,
                "channel": result.get("channel"),
                "step_status": result.get("status"),
            })

        except Exception as e:
            logger.exception("campaign step failed", extra={
                "event": "campaign_step_failed",
                "recipient_id": recipient.id,
                "campaign_id": recipient.campaign_id,
                "company_id": recipient.company_id,
                "step_order": recipient.current_step,
                "error": str(e),
            })
            results.append({
                "success": False,
                "recipient_id": recipient.id,
                "error": str(e),
            })

    return results

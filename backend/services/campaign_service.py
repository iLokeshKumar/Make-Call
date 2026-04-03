from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import (
    Campaign,
    CampaignCreate,
    CampaignRecipient,
    CampaignStep,
    CampaignStepCreate,
    Lead,
    User,
    utc_now,
    CallTask,
)

from services.outbound_call_service import create_call_task

from services.communication_service import send_email_to_lead, send_whatsapp_to_lead
from services.message_render_service import render_template_by_id

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


def enroll_leads(
    session: Session,
    company_id: int,
    campaign_id: int,
    actor_user_id: int,
    lead_ids: Iterable[int],
) -> dict:
    campaign = get_campaign_or_404(session, company_id, campaign_id)

    added = 0
    skipped = 0

    for lead_id in lead_ids:
        lead = session.exec(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.company_id == company_id,
            )
        ).first()
        if not lead:
            skipped += 1
            continue

        existing = session.exec(
            select(CampaignRecipient).where(
                CampaignRecipient.campaign_id == campaign.id,
                CampaignRecipient.lead_id == lead.id,
            )
        ).first()
        if existing:
            skipped += 1
            continue

        recipient = CampaignRecipient(
            campaign_id=campaign.id,
            company_id=company_id,
            lead_id=lead.id,
            status="pending",
            current_step=1,
            next_run_at=None,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        session.add(recipient)
        added += 1

    session.commit()
    return {"added": added, "skipped": skipped}


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
    return campaign


def list_campaigns(
    session: Session,
    company_id: int,
) -> list[Campaign]:
    return session.exec(
        select(Campaign).where(
            Campaign.company_id == company_id
        ).order_by(Campaign.created_at.desc())
    ).all()


def list_campaign_recipients(
    session: Session,
    company_id: int,
    campaign_id: int,
) -> list[CampaignRecipient]:
    get_campaign_or_404(session, company_id, campaign_id)
    return session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.company_id == company_id,
            CampaignRecipient.campaign_id == campaign_id,
        ).order_by(CampaignRecipient.created_at.desc())
    ).all()

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
        recipient.updated_at = utc_now()
        recipient.updated_by = actor_user_id
        session.add(recipient)
        session.commit()
        session.refresh(recipient)
        return recipient

    recipient.current_step = next_step.step_order
    recipient.next_run_at = utc_now() + timedelta(hours=next_step.delay_hours)
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
    query = select(CampaignRecipient).where(
        CampaignRecipient.status == "active",
        CampaignRecipient.next_run_at != None,
        CampaignRecipient.next_run_at <= now,
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
            if result.get("channel") in {"email", "whatsapp"}:
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

            results.append({"success": True, "data": result})

        except Exception as e:
            results.append({
                "success": False,
                "recipient_id": recipient.id,
                "error": str(e),
            })

    return results

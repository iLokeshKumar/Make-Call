from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, SQLModel, func, select

from auth import get_current_user
from services.core.auth_service import user_has_any_permission
from database import get_session
from models.models import EngagementEvent, Interaction, Lead, User, utc_now

router = APIRouter(prefix="/crm", tags=["CRM"])


class InteractionCreate(SQLModel):
    lead_id: int
    type: str
    content: str | None = None
    transcript: str | None = None
    direction: str | None = None
    channel: str | None = None


class InteractionListResponse(SQLModel):
    items: list[Interaction]
    total: int


@router.get("/interactions", response_model=InteractionListResponse)
async def list_interactions(
    lead_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=1000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_read_company = user_has_any_permission(session, current_user.id, {"interaction.read_company"})
    can_read_own = user_has_any_permission(session, current_user.id, {"interaction.read_own"})

    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="No permission to view interactions")

    query = select(Interaction).where(Interaction.company_id == current_user.company_id)
    count_query = select(func.count()).select_from(Interaction).where(Interaction.company_id == current_user.company_id)

    # Sales reps with only read_own see their own interactions
    if not can_read_company:
        query = query.where(Interaction.user_id == current_user.id)
        count_query = count_query.where(Interaction.user_id == current_user.id)

    if lead_id is not None:
        query = query.where(Interaction.lead_id == lead_id)
        count_query = count_query.where(Interaction.lead_id == lead_id)

    total = session.exec(count_query).one() or 0
    interactions = session.exec(
        query.order_by(Interaction.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    return InteractionListResponse(items=interactions, total=total)


@router.post("/interactions", response_model=Interaction)
async def create_interaction(
    data: InteractionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    interaction = Interaction(
        company_id=current_user.company_id,
        lead_id=data.lead_id,
        user_id=current_user.id,
        type=data.type,
        content=data.content,
        transcript=data.transcript,
        direction=data.direction,
        channel=data.channel,
        created_by=current_user.id,
        updated_by=current_user.id,
        status="logged",
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)
    return interaction


# WhatsApp

class WhatsAppSendRequest(SQLModel):
    message: str


@router.get("/leads/{lead_id}/whatsapp")
async def get_whatsapp_thread(
    lead_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all WhatsApp interactions for a lead, ordered chronologically."""
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    query = (
        select(Interaction)
        .where(
            Interaction.company_id == current_user.company_id,
            Interaction.lead_id == lead_id,
            Interaction.channel == "whatsapp",
        )
        .order_by(Interaction.created_at.asc())
    )
    total = session.exec(
        select(func.count()).select_from(Interaction).where(
            Interaction.company_id == current_user.company_id,
            Interaction.lead_id == lead_id,
            Interaction.channel == "whatsapp",
        )
    ).one()
    messages = session.exec(query.offset((page - 1) * limit).limit(limit)).all()
    return {"total": total, "lead_name": lead.name, "items": messages}


@router.post("/leads/{lead_id}/whatsapp/send")
async def send_whatsapp_to_lead_route(
    lead_id: int,
    data: WhatsAppSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Send a WhatsApp message to a lead.
    Routes to the configured telephony provider: Twilio, Exotel (or Twilio fallback for EnableX).
    Logs the interaction regardless of delivery outcome.
    """
    from services.communication.communication_service import send_whatsapp_to_lead as _send_wa
    result = _send_wa(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=lead_id,
        body=data.message,
    )
    return result


# Email

class EmailSendRequest(SQLModel):
    subject: str
    body: str


@router.get("/leads/{lead_id}/email")
async def get_email_thread(
    lead_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all email interactions for a lead, ordered chronologically."""
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    _email_filter = [
        Interaction.company_id == current_user.company_id,
        Interaction.lead_id == lead_id,
        Interaction.channel == "email",
        Interaction.status != "dismissed",
    ]
    query = (
        select(Interaction)
        .where(*_email_filter)
        .order_by(Interaction.created_at.asc())
    )
    total = session.exec(
        select(func.count()).select_from(Interaction).where(*_email_filter)
    ).one()
    emails = session.exec(query.offset((page - 1) * limit).limit(limit)).all()

    interaction_ids = [e.id for e in emails]
    events_by_interaction: dict[int, list[dict]] = {}
    if interaction_ids:
        engagement_rows = session.exec(
            select(EngagementEvent)
            .where(
                EngagementEvent.interaction_id.in_(interaction_ids),
                EngagementEvent.event_type.in_(["open", "click", "reply"]),
            )
            .order_by(EngagementEvent.created_at.asc())
        ).all()
        for ev in engagement_rows:
            events_by_interaction.setdefault(ev.interaction_id, []).append({
                "event_type": ev.event_type,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                "payload": ev.payload or {},
            })

    items = []
    for email in emails:
        d = email.dict()
        d["events"] = events_by_interaction.get(email.id, [])
        items.append(d)

    return {"total": total, "lead_email": lead.email, "items": items}


@router.delete("/leads/{lead_id}/email/{interaction_id}")
async def dismiss_email_from_thread(
    lead_id: int,
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft-remove an email interaction from the thread (sets status='dismissed')."""
    interaction = session.exec(
        select(Interaction).where(
            Interaction.id == interaction_id,
            Interaction.lead_id == lead_id,
            Interaction.company_id == current_user.company_id,
            Interaction.channel == "email",
        )
    ).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Email not found")
    interaction.status = "dismissed"
    interaction.updated_by = current_user.id
    session.add(interaction)
    session.commit()
    return {"status": "dismissed"}


@router.post("/leads/{lead_id}/email/send")
async def send_email_to_lead_route(
    lead_id: int,
    data: EmailSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Send an email to a lead and log it as an interaction."""
    from services.communication.communication_service import send_email_to_lead as _send_email
    result = _send_email(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=lead_id,
        subject=data.subject,
        body=data.body,
    )
    return result


@router.post("/email/sync")
async def trigger_imap_sync(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Trigger an immediate IMAP inbox poll for the current company."""
    from services.communication.imap_poller_service import trigger_imap_poll
    result = await trigger_imap_poll(current_user.company_id, user_id=current_user.id)
    return result

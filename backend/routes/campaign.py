from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import CampaignCreate, CampaignStepCreate, User, CampaignRecipient
from services.campaign_service import (
    add_campaign_step,
    create_campaign,
    enroll_leads,
    launch_campaign,
    list_campaign_recipients,
    list_campaign_steps,
    list_campaigns,
    pause_campaign,
    process_campaign_call_step,
    schedule_campaign_recipient_next_step,
    run_due_campaign_recipients,
    pause_campaign_recipient,
    retry_campaign_recipient,
)


router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.post("")
async def create_campaign_route(
    data: CampaignCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return create_campaign(session, current_user.company_id, current_user.id, data)


@router.get("")
async def list_campaigns_route(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.read")),
):
    return list_campaigns(session, current_user.company_id, limit=limit, offset=offset)


@router.post("/{campaign_id}/steps")
async def add_campaign_step_route(
    campaign_id: int,
    data: CampaignStepCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return add_campaign_step(session, current_user.company_id, campaign_id, current_user.id, data)


@router.get("/{campaign_id}/steps")
async def list_campaign_steps_route(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.read")),
):
    return list_campaign_steps(session, current_user.company_id, campaign_id)


@router.post("/{campaign_id}/enroll")
async def enroll_campaign_route(
    campaign_id: int,
    lead_ids: list[int],
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return enroll_leads(session, current_user.company_id, campaign_id, current_user.id, lead_ids)


@router.post("/{campaign_id}/launch")
async def launch_campaign_route(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.launch")),
):
    return launch_campaign(session, current_user.company_id, campaign_id, current_user.id)


@router.post("/{campaign_id}/pause")
async def pause_campaign_route(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return pause_campaign(session, current_user.company_id, campaign_id, current_user.id)


@router.get("/{campaign_id}/recipients")
async def list_campaign_recipients_route(
    campaign_id: int,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.read")),
):
    return list_campaign_recipients(session, current_user.company_id, campaign_id, limit=limit, offset=offset)

@router.post("/recipients/{recipient_id}/process-call-step")
async def process_campaign_call_step_route(
    recipient_id: int,
    assigned_user_id: int | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return process_campaign_call_step(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        recipient_id=recipient_id,
        assigned_user_id=assigned_user_id,
    )


@router.post("/recipients/{recipient_id}/advance")
async def advance_campaign_recipient_route(
    recipient_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    recipient = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.id == recipient_id,
            CampaignRecipient.company_id == current_user.company_id,
        )
    ).first()
    if not recipient:
        raise HTTPException(status_code=404, detail="Campaign recipient not found")

    return schedule_campaign_recipient_next_step(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        recipient=recipient,
    )

@router.post("/run-due")
async def run_due_campaigns_route(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.launch")),
):
    return run_due_campaign_recipients(
        session=session,
        actor_user_id=current_user.id,
        company_id=current_user.company_id,
    )


@router.post("/recipients/{recipient_id}/pause")
async def pause_campaign_recipient_route(
    recipient_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return pause_campaign_recipient(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        recipient_id=recipient_id,
    )


@router.post("/recipients/{recipient_id}/retry")
async def retry_campaign_recipient_route(
    recipient_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return retry_campaign_recipient(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        recipient_id=recipient_id,
    )
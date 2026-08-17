from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import Campaign, CampaignCreate, CampaignSchedule, CampaignStepCreate, CampaignStepUpdate, CampaignStepsReorder, User, CampaignRecipient, utc_now
from services.core.feature_flag_service import require_feature
from services.campaign.campaign_service import (
    add_campaign_step,
    create_campaign,
    delete_campaign_step,
    enroll_leads,
    launch_campaign,
    list_campaign_recipients,
    list_campaign_steps,
    list_campaigns,
    pause_campaign,
    process_campaign_call_step,
    reorder_campaign_steps,
    schedule_campaign_recipient_next_step,
    run_due_campaign_recipients,
    pause_campaign_recipient,
    retry_campaign_recipient,
    update_campaign_step,
)


router = APIRouter(prefix="/campaigns", tags=["Campaigns"])


@router.post("")
async def create_campaign_route(
    data: CampaignCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    require_feature(session, current_user.company_id, "campaigns")
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


@router.post("/{campaign_id}/suggest-sequence")
async def suggest_sequence_route(
    campaign_id: int,
    body: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    """LLM-suggested multi-step sequence for a given lead segment.

    Body: {"segment": "enterprise SaaS leads who downloaded the whitepaper"}
    Returns: {"suggestion": [{"channel": "email", "delay_hours": 0, "rationale": "..."}, ...]}

    Channels limited to: call, whatsapp, email.  No DB writes — frontend
    decides whether to commit each step via the existing /steps endpoint.
    """
    import json
    import re
    from credentials_service import get_company_setting_value
    from services.ai.llm import get_llm_service

    segment = (body or {}).get("segment", "").strip()
    if not segment:
        raise HTTPException(status_code=400, detail="segment is required")

    api_key = get_company_setting_value(session, current_user.company_id, "MISTRAL_API_KEY")
    llm = get_llm_service(
        "mistral",
        "You are a B2B sales sequence designer.  Output ONLY valid JSON.",
        api_key=api_key,
    )

    prompt = (
        f"Lead segment: {segment}\n\n"
        "Design a 4-6 step outbound sequence to convert this segment.  Each step uses one of "
        "channels: call, whatsapp, email.  delay_hours is hours to wait BEFORE this step "
        "(0 for first).  Keep rationales short (<60 chars).\n\n"
        "Return ONLY a JSON object:\n"
        '{"suggestion": [{"channel": "email", "delay_hours": 0, "rationale": "..."}, ...]}\n'
        "No markdown, no explanation outside JSON."
    )

    llm.add_user_message(prompt)
    raw = ""
    try:
        async for chunk in llm.stream():
            if chunk.get("type") == "finished":
                raw = chunk.get("full_reply", raw)
                break
            elif chunk.get("type") == "token":
                raw += chunk.get("content", "")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"LLM stream failed: {exc}")

    # Tolerant parse — strip code fences, find first {...}
    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw)
        if m:
            try:
                parsed = json.loads(m.group(0))
            except Exception:
                parsed = None

    if not parsed or "suggestion" not in parsed:
        raise HTTPException(status_code=502, detail=f"Could not parse LLM JSON. Raw: {raw[:300]}")

    # Defensive: clamp channels + delays
    cleaned = []
    for s in parsed.get("suggestion", [])[:8]:
        ch = (s.get("channel") or "").lower()
        if ch not in ("call", "whatsapp", "email"):
            continue
        try:
            delay = max(0, min(int(s.get("delay_hours", 24)), 24 * 30))
        except (TypeError, ValueError):
            delay = 24
        cleaned.append({
            "channel": ch,
            "delay_hours": delay,
            "rationale": (s.get("rationale") or "")[:200],
        })
    return {"suggestion": cleaned, "campaign_id": campaign_id}


@router.get("/{campaign_id}/steps")
async def list_campaign_steps_route(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.read")),
):
    return list_campaign_steps(session, current_user.company_id, campaign_id)


@router.delete("/{campaign_id}/steps/{step_id}", status_code=204)
async def delete_campaign_step_route(
    campaign_id: int,
    step_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    delete_campaign_step(session, current_user.company_id, campaign_id, step_id)


@router.patch("/{campaign_id}/steps/{step_id}")
async def update_campaign_step_route(
    campaign_id: int,
    step_id: int,
    data: CampaignStepUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return update_campaign_step(
        session, current_user.company_id, campaign_id, step_id, current_user.id, data
    )


@router.put("/{campaign_id}/steps/reorder")
async def reorder_campaign_steps_route(
    campaign_id: int,
    data: CampaignStepsReorder,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    return reorder_campaign_steps(
        session, current_user.company_id, campaign_id, current_user.id, data
    )


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
    require_feature(session, current_user.company_id, "campaigns")
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


# ---------------------------------------------------------------------------
# Campaign Schedule endpoints
# ---------------------------------------------------------------------------

class CampaignScheduleUpsert(BaseModel):
    agent_id: Optional[int] = None
    start_date: datetime
    end_date: Optional[datetime] = None
    daily_start_hour: int = 9
    daily_end_hour: int = 18
    days_of_week: list[int] = [0, 1, 2, 3, 4]
    timezone: str = "Asia/Kolkata"
    max_concurrent_calls: int = 5
    calls_per_minute: int = 10


@router.get("/{campaign_id}/schedule")
async def get_campaign_schedule(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.read")),
):
    sched = session.exec(
        select(CampaignSchedule).where(
            CampaignSchedule.campaign_id == campaign_id,
            CampaignSchedule.company_id == current_user.company_id,
        )
    ).first()
    if not sched:
        raise HTTPException(status_code=404, detail="No schedule found")
    return sched


@router.post("/{campaign_id}/schedule")
async def upsert_campaign_schedule(
    campaign_id: int,
    data: CampaignScheduleUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    campaign = session.exec(
        select(Campaign).where(
            Campaign.id == campaign_id,
            Campaign.company_id == current_user.company_id,
        )
    ).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    sched = session.exec(
        select(CampaignSchedule).where(
            CampaignSchedule.campaign_id == campaign_id,
            CampaignSchedule.company_id == current_user.company_id,
        )
    ).first()

    if sched:
        sched.agent_id = data.agent_id
        sched.start_date = data.start_date
        sched.end_date = data.end_date
        sched.daily_start_hour = data.daily_start_hour
        sched.daily_end_hour = data.daily_end_hour
        sched.days_of_week = data.days_of_week
        sched.timezone = data.timezone
        sched.max_concurrent_calls = data.max_concurrent_calls
        sched.calls_per_minute = data.calls_per_minute
        sched.status = "active"
        sched.next_run_at = data.start_date
        sched.updated_at = utc_now()
        sched.updated_by = current_user.id
    else:
        sched = CampaignSchedule(
            company_id=current_user.company_id,
            campaign_id=campaign_id,
            agent_id=data.agent_id,
            start_date=data.start_date,
            end_date=data.end_date,
            daily_start_hour=data.daily_start_hour,
            daily_end_hour=data.daily_end_hour,
            days_of_week=data.days_of_week,
            timezone=data.timezone,
            max_concurrent_calls=data.max_concurrent_calls,
            calls_per_minute=data.calls_per_minute,
            status="active",
            next_run_at=data.start_date,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
    session.add(sched)
    session.commit()
    session.refresh(sched)
    return sched


@router.patch("/{campaign_id}/schedule/pause")
async def pause_campaign_schedule(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    sched = session.exec(
        select(CampaignSchedule).where(
            CampaignSchedule.campaign_id == campaign_id,
            CampaignSchedule.company_id == current_user.company_id,
        )
    ).first()
    if not sched:
        raise HTTPException(status_code=404, detail="No schedule found")
    sched.status = "paused"
    sched.updated_at = utc_now()
    sched.updated_by = current_user.id
    session.add(sched)
    session.commit()
    return {"status": "paused"}


@router.patch("/{campaign_id}/schedule/resume")
async def resume_campaign_schedule(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    sched = session.exec(
        select(CampaignSchedule).where(
            CampaignSchedule.campaign_id == campaign_id,
            CampaignSchedule.company_id == current_user.company_id,
        )
    ).first()
    if not sched:
        raise HTTPException(status_code=404, detail="No schedule found")
    sched.status = "active"
    sched.updated_at = utc_now()
    sched.updated_by = current_user.id
    session.add(sched)
    session.commit()
    return {"status": "active"}


@router.delete("/{campaign_id}/schedule")
async def delete_campaign_schedule(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    sched = session.exec(
        select(CampaignSchedule).where(
            CampaignSchedule.campaign_id == campaign_id,
            CampaignSchedule.company_id == current_user.company_id,
        )
    ).first()
    if not sched:
        raise HTTPException(status_code=404, detail="No schedule found")
    session.delete(sched)
    session.commit()
    return {"status": "deleted"}


@router.post("/{campaign_id}/run-now")
async def run_campaign_now(
    campaign_id: int,
    force: bool = False,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    """Manually fire queued call tasks for this campaign. If force=true, bypasses time window check."""
    from services.campaign.dialer_service import run_batch_dialer_for_campaign
    results = run_batch_dialer_for_campaign(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        campaign_id=campaign_id,
        limit=limit,
        force=force,
    )
    return {"campaign_id": campaign_id, "results": results}
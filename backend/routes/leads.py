from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select, func, delete

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import (
    Appointment,
    CallCoachScore,
    CallTask,
    CampaignRecipient,
    Interaction,
    LatencyLog,
    Lead,
    LeadCreate,
    LeadRequirement,
    LeadUpdate,
    OptOut,
    Outcome,
    Quote,
    QuoteItem,
    User,
    utc_now,
)
from utils.timezone_utils import detect_timezone
from services.core.auth_service import user_has_any_permission
from services.leads.demand_generation_service import enrich_lead_if_needed, score_lead, trigger_new_lead_outreach
from services.leads.opt_out_service import unsubscribe_lead

router = APIRouter(prefix="/crm", tags=["CRM"])


@router.post("/leads", response_model=Lead)
async def create_lead(
    data: LeadCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    owner_user_id = data.owner_user_id or current_user.id

    owner = session.exec(
        select(User).where(
            User.id == owner_user_id,
            User.company_id == current_user.company_id,
            User.is_active.is_(True),
        )
    ).first()
    if not owner:
        raise HTTPException(status_code=400, detail="Invalid lead owner")

    phone = data.normalized_phone.strip()

    # Check for active duplicate
    existing = session.exec(
        select(Lead).where(
            Lead.company_id == current_user.company_id,
            Lead.normalized_phone == phone,
            Lead.deleted_at.is_(None),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Lead already exists for this company")

    # Restore soft-deleted lead if one exists with the same phone
    deleted_lead = session.exec(
        select(Lead).where(
            Lead.company_id == current_user.company_id,
            Lead.normalized_phone == phone,
            Lead.deleted_at.isnot(None),
        )
    ).first()

    if deleted_lead:
        deleted_lead.deleted_at = None
        deleted_lead.name = data.name.strip()
        deleted_lead.email = data.email.strip().lower() if data.email else deleted_lead.email
        deleted_lead.owner_user_id = owner_user_id
        deleted_lead.status = data.status or "new"
        deleted_lead.qualification_status = "unqualified"
        deleted_lead.notes = data.notes
        deleted_lead.ism_stage = "new"
        deleted_lead.updated_by = current_user.id
        deleted_lead.updated_at = utc_now()
        session.add(deleted_lead)
        session.commit()
        session.refresh(deleted_lead)
        lead = deleted_lead
    else:
        lead = Lead(
            company_id=current_user.company_id,
            owner_user_id=owner_user_id,
            name=data.name.strip(),
            normalized_phone=phone,
            email=data.email.strip().lower() if data.email else None,
            status=data.status or "new",
            notes=data.notes,
            source="manual",
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        session.add(lead)
        session.commit()
        session.refresh(lead)
    try:
        trigger_new_lead_outreach(
            session=session,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            lead_id=lead.id,
        )
        session.refresh(lead)
    except Exception:
        # Lead creation should not fail if auto-trigger logic is unavailable or misconfigured.
        pass
    return lead


@router.get("/leads")
async def list_leads(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=1000),
    owner_user_id: int | None = None,
    search: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_read_company = user_has_any_permission(session, current_user.id, {"lead.read_company"})
    can_read_own = user_has_any_permission(session, current_user.id, {"lead.read_own"})

    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(Lead.company_id == current_user.company_id, Lead.deleted_at.is_(None))
    count_query = select(func.count()).select_from(Lead).where(Lead.company_id == current_user.company_id, Lead.deleted_at.is_(None))

    if can_read_company:
        if owner_user_id is not None:
            query = query.where(Lead.owner_user_id == owner_user_id)
            count_query = count_query.where(Lead.owner_user_id == owner_user_id)
    else:
        query = query.where(Lead.owner_user_id == current_user.id)
        count_query = count_query.where(Lead.owner_user_id == current_user.id)

    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            Lead.name.ilike(s) |
            Lead.company_name.ilike(s) |
            Lead.normalized_phone.ilike(s)
        )
        count_query = count_query.where(
            Lead.name.ilike(s) |
            Lead.company_name.ilike(s) |
            Lead.normalized_phone.ilike(s)
        )

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Lead.created_at.desc()).offset((page - 1) * limit).limit(limit)
    ).all()

    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/leads/{lead_id}", response_model=Lead)
async def get_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_read_company = user_has_any_permission(session, current_user.id, {"lead.read_company"})
    can_read_own = user_has_any_permission(session, current_user.id, {"lead.read_own"})

    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
        Lead.deleted_at.is_(None),
    )
    if not can_read_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return lead


@router.put("/leads/{lead_id}", response_model=Lead)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
        Lead.deleted_at.is_(None),
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    payload = data.model_dump(exclude_unset=True)

    if "owner_user_id" in payload and payload["owner_user_id"] is not None:
        owner = session.exec(
            select(User).where(
                User.id == payload["owner_user_id"],
                User.company_id == current_user.company_id,
                User.is_active.is_(True),
            )
        ).first()
        if not owner:
            raise HTTPException(status_code=400, detail="Invalid lead owner")

    if "normalized_phone" in payload and payload["normalized_phone"] != lead.normalized_phone:
        duplicate = session.exec(
            select(Lead).where(
                Lead.company_id == current_user.company_id,
                Lead.normalized_phone == payload["normalized_phone"],
                Lead.id != lead.id,
                Lead.deleted_at.is_(None),
            )
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Phone already used in this company")

    for key, value in payload.items():
        setattr(lead, key, value)

    lead.updated_at = utc_now()
    lead.updated_by = current_user.id
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return lead


@router.patch("/leads/{lead_id}", response_model=Lead)
async def patch_lead(
    lead_id: int,
    data: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Partial update — accepts any subset of Lead fields (e.g., ism_stage, preferred_language)."""
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})
    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
        Lead.deleted_at.is_(None),
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Only allow known Lead fields
    allowed = {c.key for c in Lead.__table__.columns} - {"id", "company_id", "created_at", "created_by"}
    for key, value in data.items():
        if key in allowed:
            setattr(lead, key, value)

    lead.updated_at = utc_now()
    lead.updated_by = current_user.id
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return lead


@router.delete("/leads/{lead_id}")
async def delete_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_delete_company = user_has_any_permission(session, current_user.id, {"lead.delete_company"})
    can_delete_own = user_has_any_permission(session, current_user.id, {"lead.delete_own"})

    if not can_delete_company and not can_delete_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
        Lead.deleted_at.is_(None),
    )
    if not can_delete_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Soft delete — preserve all history (calls, quotes, interactions, latency logs)
    lead.deleted_at = utc_now()
    lead.updated_at = utc_now()
    lead.updated_by = current_user.id
    session.add(lead)
    session.commit()
    return {"message": "Lead deleted"}


@router.get("/leads/{lead_id}/agent-actions")
async def agent_actions_timeline(
    lead_id: int,
    limit: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Unified agent-actions timeline for a lead: AgentTask + EngagementEvent + Interaction
    merged, sorted desc by timestamp. Used by the 'Agent Actions Timeline' Lead 360 panel.
    """
    from models.models import AgentTask, EngagementEvent

    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
            Lead.deleted_at.is_(None),
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    tasks = session.exec(
        select(AgentTask)
        .where(AgentTask.lead_id == lead_id, AgentTask.company_id == current_user.company_id)
        .order_by(AgentTask.created_at.desc())
        .limit(limit)
    ).all()
    events = session.exec(
        select(EngagementEvent)
        .where(EngagementEvent.lead_id == lead_id, EngagementEvent.company_id == current_user.company_id)
        .order_by(EngagementEvent.created_at.desc())
        .limit(limit)
    ).all()
    interactions = session.exec(
        select(Interaction)
        .where(Interaction.lead_id == lead_id, Interaction.company_id == current_user.company_id)
        .order_by(Interaction.created_at.desc())
        .limit(limit)
    ).all()

    merged: list[dict] = []
    for t in tasks:
        merged.append({
            "kind": "agent_task",
            "id": t.id,
            "timestamp": (t.updated_at or t.created_at).isoformat() if (t.updated_at or t.created_at) else None,
            "agent": t.assigned_agent,
            "task_type": t.task_type,
            "status": t.status,
            "requires_approval": t.requires_approval,
            "input": t.input_json,
            "output": t.output_json,
            "error": t.error_json,
            "undoable": t.status in {"pending", "awaiting_approval", "approved"},
            "takeoverable": t.status in {"pending", "awaiting_approval", "running"},
        })
    for e in events:
        merged.append({
            "kind": "engagement_event",
            "id": e.id,
            "timestamp": e.created_at.isoformat() if e.created_at else None,
            "event_type": e.event_type,
            "channel": e.channel,
            "payload": e.payload,
        })
    for i in interactions:
        merged.append({
            "kind": "interaction",
            "id": i.id,
            "timestamp": (i.started_at or i.created_at).isoformat() if (i.started_at or i.created_at) else None,
            "type": i.type,
            "channel": i.channel,
            "direction": i.direction,
            "status": i.status,
            "content": i.content,
        })

    merged.sort(key=lambda r: r["timestamp"] or "", reverse=True)
    return {"lead_id": lead_id, "items": merged[:limit]}


@router.post("/agent-tasks/{task_id}/undo")
async def undo_agent_task(
    task_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending/awaiting/approved AgentTask before it runs."""
    from models.models import AgentTask

    task = session.exec(
        select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.company_id == current_user.company_id,
        )
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status not in {"pending", "awaiting_approval", "approved"}:
        raise HTTPException(status_code=409, detail=f"Cannot undo task in status '{task.status}'")
    task.status = "rejected"
    task.error_json = {**(task.error_json or {}), "undo_by": current_user.id, "undo_reason": "user_undo"}
    task.updated_at = utc_now()
    task.updated_by = current_user.id
    session.add(task)
    session.commit()
    session.refresh(task)
    return {"id": task.id, "status": task.status}


@router.post("/agent-tasks/{task_id}/takeover")
async def takeover_agent_task(
    task_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Mark a task as needs_human — worker skips it; operator owns follow-up."""
    from models.models import AgentTask

    task = session.exec(
        select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.company_id == current_user.company_id,
        )
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in {"done", "failed", "rejected"}:
        raise HTTPException(status_code=409, detail=f"Cannot takeover task in status '{task.status}'")
    task.status = "needs_human"
    task.error_json = {**(task.error_json or {}), "takeover_by": current_user.id}
    task.updated_at = utc_now()
    task.updated_by = current_user.id
    session.add(task)
    session.commit()
    session.refresh(task)
    return {"id": task.id, "status": task.status}


@router.get("/leads/{lead_id}/next-action-explain")
async def explain_next_action(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return which IsmRule would fire for this lead right now, or None if no rule
    matches. Frontend uses this to render an 'Explain Next Action' panel.
    """
    from agents.ism_rules_engine import evaluate_rules, parse_action

    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
            Lead.deleted_at.is_(None),
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    matched = evaluate_rules(session, current_user.company_id, lead)
    result: dict = {
        "lead_id": lead_id,
        "ism_stage": lead.ism_stage,
        "matched_rule": None,
        "action": None,
    }
    if matched:
        verb, arg = parse_action(matched.then_action or "")
        result["matched_rule"] = {
            "id": matched.id,
            "name": matched.name,
            "priority": matched.priority,
            "when_json": matched.when_json,
            "then_action": matched.then_action,
        }
        result["action"] = {"verb": verb, "argument": arg}
    return result


@router.get("/ai-insights")
async def ai_insights(
    lead_id: int = Query(default=None, ge=1),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")

    lead = session.get(Lead, lead_id)
    if not lead or lead.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Lead not found")

    interactions = session.exec(
        select(Interaction)
        .where(
            Interaction.company_id == current_user.company_id,
            Interaction.lead_id == lead_id,
        )
        .order_by(Interaction.created_at.desc())
    ).all()

    manual_notes = [i for i in interactions if (i.type or "").lower() == "note"]
    call_interactions = [i for i in interactions if (i.type or "").lower().startswith("call")]
    completed_calls = [i for i in call_interactions if (i.status or "").lower() == "completed"]

    summary_parts = [
        f"{lead.name} is currently in the \"{lead.status}\" stage.",
        f"{len(interactions)} interactions have been logged.",
    ]

    if manual_notes:
        summary_parts.append(f"{len(manual_notes)} manual notes capture your latest context.")

    if call_interactions:
        summary_parts.append(f"{len(completed_calls)} of {len(call_interactions)} calls have been completed.")
    elif lead.next_action:
        summary_parts.append(f"Next action: {lead.next_action}.")

    if lead.next_action_due_at:
        summary_parts.append(f"Due by {lead.next_action_due_at}.")

    return {"summary": " ".join(summary_parts)}


@router.post("/leads/{lead_id}/enrich")
async def enrich_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Enrich a lead using the demand generation service."""
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = enrich_lead_if_needed(session, current_user.company_id, current_user.id, lead_id)
    return {"lead_id": lead_id, "enriched": result, "message": "Enrichment complete." if result else "No enrichment needed or no data found."}


@router.get("/leads/{lead_id}/enrichment-trace")
async def get_enrichment_trace(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return the waterfall enrichment trace for a lead:
    DB → Apollo → Lusha → Validation
    """
    from credentials_service import get_company_credential

    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    def _has(val) -> bool:
        return bool(val and str(val).strip())

    db_fields = {
        "name": _has(lead.name),
        "email": _has(lead.email),
        "phone": _has(lead.normalized_phone),
        "website": _has(lead.website),
        "city": _has(lead.city),
        "industry": _has(lead.industry),
        "company_name": _has(lead.company_name),
        "designation": _has(lead.designation),
    }
    db_populated = [k for k, v in db_fields.items() if v]
    db_missing = [k for k, v in db_fields.items() if not v]

    apollo_key = get_company_credential(session, current_user.company_id, "APOLLO_API_KEY")
    apollo_configured = bool(apollo_key)
    apollo_used = (lead.source or "").lower() in {"apollo api", "apollo"}
    apollo_status = "enriched" if apollo_used else ("available" if apollo_configured else "not_configured")

    lusha_key = get_company_credential(session, current_user.company_id, "LUSHA_API_KEY")
    lusha_configured = bool(lusha_key)
    lusha_status = "available" if lusha_configured else "not_configured"

    email_valid = _has(lead.email) and "@" in lead.email and "." in lead.email.split("@")[-1]
    phone_valid = _has(lead.normalized_phone) and lead.normalized_phone.startswith("+")
    validation_status = "passed" if (email_valid or phone_valid) else "partial"

    return {
        "lead_id": lead_id,
        "enrichment_status": lead.enrichment_status,
        "last_enriched_at": lead.last_enriched_at.isoformat() if lead.last_enriched_at else None,
        "steps": [
            {
                "name": "Database",
                "key": "db",
                "status": "enriched" if len(db_populated) >= 4 else ("partial" if db_populated else "empty"),
                "populated_fields": db_populated,
                "missing_fields": db_missing,
                "description": f"{len(db_populated)}/{len(db_fields)} fields populated from CRM data",
            },
            {
                "name": "Apollo.io",
                "key": "apollo",
                "status": apollo_status,
                "configured": apollo_configured,
                "description": "B2B contact & company enrichment via Apollo API",
            },
            {
                "name": "Lusha",
                "key": "lusha",
                "status": lusha_status,
                "configured": lusha_configured,
                "description": "Direct-dial phone & verified email via Lusha API",
            },
            {
                "name": "Validation",
                "key": "validation",
                "status": validation_status,
                "email_valid": email_valid,
                "phone_valid": phone_valid,
                "description": "Email format check + E.164 phone number validation",
            },
        ],
    }


@router.post("/leads/{lead_id}/rescore")
async def rescore_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Rescore a lead using the demand generation service."""
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    enrich_result = enrich_lead_if_needed(session, current_user.company_id, current_user.id, lead_id)
    score_result = score_lead(session, current_user.company_id, lead_id)

    return {
        "lead_id": lead_id,
        "enrichment": enrich_result,
        "scoring": score_result,
    }


@router.post("/leads/{lead_id}/opt-out")
async def opt_out_lead(
    lead_id: int,
    channel: str = Query(..., description="Channel to opt out from (email, whatsapp, call, sms)"),
    reason: str | None = Query(None, description="Optional reason for opt-out"),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.update")),
):
    """Opt out a lead from a specific communication channel."""
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if channel not in {"email", "whatsapp", "call", "sms"}:
        raise HTTPException(status_code=400, detail="Invalid channel. Must be one of: email, whatsapp, call, sms")

    unsubscribe_lead(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=lead_id,
        channel=channel,
        reason=reason,
    )

    return {
        "lead_id": lead_id,
        "channel": channel,
        "opted_out": True,
        "reason": reason,
    }


@router.get("/leads/{lead_id}/best-call-times")
async def get_best_call_times(
    lead_id: int,
    n_windows: int = Query(default=5, ge=1, le=20),
    lookahead_hours: int = Query(default=72, ge=12, le=168),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return the top N predicted call windows for this lead, ranked by connection probability.
    Uses a GradientBoostingClassifier trained on the company's own historical outcomes,
    falling back to a heuristic frequency table if training data is insufficient.
    """
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    from services.call.predictive_dialer_service import get_best_call_windows
    return get_best_call_windows(
        session=session,
        company_id=current_user.company_id,
        lead_id=lead_id,
        n_windows=n_windows,
        lookahead_hours=lookahead_hours,
    )


@router.get("/leads/{lead_id}/deal-timeline")
async def get_lead_deal_timeline(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Returns a unified, chronological deal timeline for a lead:
    appointments (demos/meetings) and quotes (with line items).
    """
    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == current_user.company_id)
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    events: list[dict] = []

    appointments = session.exec(
        select(Appointment)
        .where(Appointment.lead_id == lead_id, Appointment.company_id == current_user.company_id)
        .order_by(Appointment.appointment_time.asc())
    ).all()

    for appt in appointments:
        demo_type = "Demo"
        products_label = ""
        location = ""
        extra_notes = ""
        if appt.notes:
            for part in appt.notes.split(";"):
                part = part.strip()
                if part.lower().startswith("demo type="):
                    demo_type = part.split("=", 1)[1].strip()
                elif part.lower().startswith("products="):
                    products_label = part.split("=", 1)[1].strip()
                elif part.lower().startswith("location="):
                    location = part.split("=", 1)[1].strip()
                elif part.lower().startswith("notes="):
                    extra_notes = part.split("=", 1)[1].strip()

        events.append({
            "kind": "appointment",
            "id": appt.id,
            "date": appt.appointment_time.isoformat(),
            "status": appt.status,
            "demo_type": demo_type,
            "products": products_label or None,
            "location": location or None,
            "notes": extra_notes or appt.notes,
            "meeting_link": appt.meeting_link,
        })

    quotes = session.exec(
        select(Quote)
        .where(Quote.lead_id == lead_id, Quote.company_id == current_user.company_id)
        .order_by(Quote.created_at.asc())
    ).all()

    for q in quotes:
        items = session.exec(
            select(QuoteItem).where(QuoteItem.quote_id == q.id)
        ).all()

        events.append({
            "kind": "quote",
            "id": q.id,
            "quote_number": q.quote_number,
            "date": (q.sent_at or q.created_at).isoformat() if (q.sent_at or q.created_at) else None,
            "status": q.status,
            "currency": q.currency,
            "total_amount": str(q.total_amount) if q.total_amount is not None else None,
            "valid_until": q.valid_until.isoformat() if q.valid_until else None,
            "sent_at": q.sent_at.isoformat() if q.sent_at else None,
            "opened_at": q.opened_at.isoformat() if q.opened_at else None,
            "accepted_at": q.accepted_at.isoformat() if q.accepted_at else None,
            "rejected_at": q.rejected_at.isoformat() if q.rejected_at else None,
            "notes": q.notes,
            "items": [
                {
                    "product_name": item.product_name_snapshot,
                    "sku": item.sku_snapshot,
                    "quantity": item.quantity,
                    "unit_price": str(item.unit_price),
                    "discount_percent": str(item.discount_percent),
                    "line_total": str(item.line_total),
                }
                for item in items
            ],
        })

    events.sort(key=lambda e: e.get("date") or "")

    return {"lead_id": lead_id, "events": events}


@router.get("/leads/{lead_id}/context")
async def get_lead_context(
    lead_id: int,
    interaction_limit: int = Query(30, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Single-request comprehensive lead context bundle:
    lead + interactions + call tasks + requirement + deal timeline
    + feedback + opt-out channels + latest coach score + detected timezone.
    Replaces 6 separate API calls on the lead detail page.
    """
    can_read_company = user_has_any_permission(session, current_user.id, {"lead.read_company"})
    can_read_own     = user_has_any_permission(session, current_user.id, {"lead.read_own"})
    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    lead_query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
        Lead.deleted_at.is_(None),
    )
    if not can_read_company:
        lead_query = lead_query.where(Lead.owner_user_id == current_user.id)
    lead = session.exec(lead_query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Detect / confirm timezone
    effective_tz = lead.timezone or detect_timezone(lead.city, lead.state, lead.country)

    # Interactions (most recent first)
    interactions = session.exec(
        select(Interaction)
        .where(Interaction.lead_id == lead_id, Interaction.company_id == current_user.company_id)
        .order_by(Interaction.created_at.desc())
        .limit(interaction_limit)
    ).all()

    # Call tasks
    tasks = session.exec(
        select(CallTask)
        .where(CallTask.lead_id == lead_id, CallTask.company_id == current_user.company_id)
        .order_by(CallTask.created_at.desc())
        .limit(20)
    ).all()

    # Requirement
    requirement = session.exec(
        select(LeadRequirement).where(
            LeadRequirement.lead_id == lead_id,
            LeadRequirement.company_id == current_user.company_id,
        )
    ).first()

    # Quotes (most recent 10) with line items
    quotes_raw = session.exec(
        select(Quote)
        .where(Quote.lead_id == lead_id, Quote.company_id == current_user.company_id, Quote.deleted_at.is_(None))
        .order_by(Quote.created_at.desc())
        .limit(10)
    ).all()
    quote_ids = [q.id for q in quotes_raw]
    all_items = session.exec(select(QuoteItem).where(QuoteItem.quote_id.in_(quote_ids))).all() if quote_ids else []
    items_by_quote: dict[int, list] = {}
    for it in all_items:
        items_by_quote.setdefault(it.quote_id, []).append(it)

    quotes = []
    for q in quotes_raw:
        quotes.append({
            "id": q.id, "quote_number": q.quote_number, "status": q.status,
            "currency": q.currency,
            "total_amount": str(q.total_amount) if q.total_amount is not None else None,
            "valid_until": q.valid_until.isoformat() if q.valid_until else None,
            "sent_at": q.sent_at.isoformat() if q.sent_at else None,
            "opened_at": q.opened_at.isoformat() if q.opened_at else None,
            "accepted_at": q.accepted_at.isoformat() if q.accepted_at else None,
            "rejected_at": q.rejected_at.isoformat() if q.rejected_at else None,
            "notes": q.notes,
            "created_at": q.created_at.isoformat() if q.created_at else None,
            "items": [
                {
                    "product_name": i.product_name_snapshot, "sku": i.sku_snapshot,
                    "quantity": i.quantity, "unit_price": str(i.unit_price),
                    "discount_percent": str(i.discount_percent), "line_total": str(i.line_total),
                }
                for i in items_by_quote.get(q.id, [])
            ],
        })

    # Appointments
    appointments = session.exec(
        select(Appointment)
        .where(Appointment.lead_id == lead_id, Appointment.company_id == current_user.company_id)
        .order_by(Appointment.appointment_time.asc())
    ).all()

    # Feedback
    from models.models import Feedback  # local import to avoid circular issues
    feedback = session.exec(
        select(Feedback)
        .where(Feedback.lead_id == lead_id, Feedback.company_id == current_user.company_id)
        .order_by(Feedback.created_at.desc())
        .limit(20)
    ).all()

    # Opt-out channels
    opt_outs = session.exec(
        select(OptOut).where(
            OptOut.lead_id == lead_id, OptOut.company_id == current_user.company_id
        )
    ).all()
    opt_out_channels = [o.channel for o in opt_outs]

    # Latest coach score (most recent call interaction with a score)
    latest_coach_score = session.exec(
        select(CallCoachScore)
        .where(CallCoachScore.lead_id == lead_id, CallCoachScore.company_id == current_user.company_id)
        .order_by(CallCoachScore.id.desc())
        .limit(1)
    ).first()

    return {
        "lead": lead,
        "effective_timezone": effective_tz,
        "interactions": interactions,
        "tasks": tasks,
        "requirement": requirement,
        "quotes": quotes,
        "appointments": [
            {
                "id": a.id,
                "appointment_time": a.appointment_time.isoformat() if a.appointment_time else None,
                "status": a.status, "notes": a.notes,
            }
            for a in appointments
        ],
        "feedback": [
            {
                "id": f.id, "rating": f.rating, "comment": f.comment,
                "source": f.source, "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in feedback
        ],
        "opt_out_channels": opt_out_channels,
        "latest_coach_score": latest_coach_score,
    }

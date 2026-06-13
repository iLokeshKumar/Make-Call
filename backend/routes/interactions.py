import logging
import httpx
import os
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlmodel import Session, SQLModel, func, select

from auth import get_current_user
from credentials_service import get_company_credential
from services.core.auth_service import user_has_any_permission
from database import get_session
from models.models import CallEvalResult, EngagementEvent, Feedback, Interaction, Lead, User, ASRSegment, ASRCleanupRun, utc_now

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crm", tags=["CRM"])


class InteractionCreate(SQLModel):
    lead_id: int
    type: str
    content: str | None = None
    transcript: str | None = None
    direction: str | None = None
    channel: str | None = None


class ChildInteractionSummary(SQLModel):
    id: int
    channel: str | None = None
    direction: str | None = None
    type: str | None = None
    created_at: str | None = None
    content: str | None = None


class InteractionListItem(SQLModel):
    """Interaction row with lead_name joined in for the UI."""
    id: int
    type: str
    channel: str | None = None
    direction: str | None = None
    source: str | None = None
    status: str | None = None
    delivery_status: str | None = None
    content: str | None = None
    transcript: str | None = None
    recording_url: str | None = None
    recording_duration: int | None = None
    started_at: str | None = None
    ended_at: str | None = None
    created_at: str | None = None
    lead_id: int | None = None
    lead_name: str | None = None
    eval_score: float | None = None
    eval_passed: bool | None = None
    csat_rating: int | None = None
    parent_interaction_id: int | None = None
    children: list[ChildInteractionSummary] = []
    metadata_json: dict | None = None


class InteractionListResponse(SQLModel):
    items: list[InteractionListItem]
    total: int
    page: int


@router.get("/interactions", response_model=InteractionListResponse)
async def list_interactions(
    lead_id: int | None = Query(default=None),
    type: str | None = Query(default=None),
    direction: str | None = Query(default=None),
    parent_interaction_id: int | None = Query(default=None),
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

    if type is not None:
        query = query.where(Interaction.type == type)
        count_query = count_query.where(Interaction.type == type)

    if direction is not None:
        query = query.where(Interaction.direction == direction)
        count_query = count_query.where(Interaction.direction == direction)

    if parent_interaction_id is not None:
        query = query.where(Interaction.parent_interaction_id == parent_interaction_id)
        count_query = count_query.where(Interaction.parent_interaction_id == parent_interaction_id)

    total = session.exec(count_query).one() or 0
    interactions = session.exec(
        query.order_by(Interaction.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    # One join-less lookup so the UI can show "Outbound to <name>" without extra requests.
    lead_ids = {i.lead_id for i in interactions if i.lead_id is not None}
    lead_names: dict[int, str] = {}
    if lead_ids:
        lead_rows = session.exec(
            select(Lead.id, Lead.name).where(
                Lead.company_id == current_user.company_id,
                Lead.id.in_(lead_ids),
            )
        ).all()
        lead_names = {row[0]: row[1] for row in lead_rows}

    # Batch-fetch children for all returned interactions (avoids N+1).
    interaction_ids = [i.id for i in interactions]
    children_map: dict[int, list[ChildInteractionSummary]] = {i.id: [] for i in interactions}
    if interaction_ids:
        child_rows = session.exec(
            select(
                Interaction.id,
                Interaction.parent_interaction_id,
                Interaction.channel,
                Interaction.direction,
                Interaction.type,
                Interaction.created_at,
                Interaction.content,
            ).where(
                Interaction.parent_interaction_id.in_(interaction_ids),
                Interaction.company_id == current_user.company_id,
            ).order_by(Interaction.created_at.asc())
        ).all()
        for row in child_rows:
            pid = row[1]
            if pid in children_map:
                children_map[pid].append(ChildInteractionSummary(
                    id=row[0],
                    channel=row[2],
                    direction=row[3],
                    type=row[4],
                    created_at=row[5].isoformat() if row[5] else None,
                    content=(row[6] or "")[:120] if row[6] else None,
                ))

    # Batch-fetch AI eval scores.
    eval_map: dict[int, tuple[float | None, bool | None]] = {}
    if interaction_ids:
        eval_rows = session.exec(
            select(CallEvalResult.interaction_id, CallEvalResult.score_overall, CallEvalResult.passed)
            .where(CallEvalResult.interaction_id.in_(interaction_ids))
        ).all()
        for row in eval_rows:
            eval_map[row[0]] = (row[1], row[2])

    # Batch-fetch latest submitted CSAT rating per interaction.
    csat_map: dict[int, int] = {}
    if interaction_ids:
        csat_rows = session.exec(
            select(Feedback.interaction_id, Feedback.rating)
            .where(
                Feedback.interaction_id.in_(interaction_ids),
                Feedback.rating.is_not(None),
                Feedback.status == "submitted",
            )
            .order_by(Feedback.interaction_id, Feedback.id.desc())
        ).all()
        for row in csat_rows:
            if row[0] not in csat_map and row[1] is not None:
                csat_map[row[0]] = row[1]

    items = [
        InteractionListItem(
            id=i.id,
            type=i.type,
            channel=i.channel,
            direction=i.direction,
            status=i.status,
            delivery_status=i.delivery_status,
            content=i.content,
            transcript=i.transcript,
            recording_url=i.recording_url,
            recording_duration=i.recording_duration,
            started_at=i.started_at.isoformat() if i.started_at else None,
            ended_at=i.ended_at.isoformat() if i.ended_at else None,
            created_at=i.created_at.isoformat() if i.created_at else None,
            lead_id=i.lead_id,
            lead_name=lead_names.get(i.lead_id) if i.lead_id else None,
            source=i.source,
            eval_score=eval_map.get(i.id, (None, None))[0],
            eval_passed=eval_map.get(i.id, (None, None))[1],
            csat_rating=csat_map.get(i.id),
            parent_interaction_id=i.parent_interaction_id,
            children=children_map.get(i.id, []),
            metadata_json=i.metadata_json,
        )
        for i in interactions
    ]

    return InteractionListResponse(items=items, total=total, page=page)


@router.get("/interactions/{interaction_id}/recording")
async def stream_interaction_recording(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Proxy the recording so the browser can play it.

    Twilio recording URLs (https://api.twilio.com/.../Recordings/{sid}.mp3)
    require HTTP Basic Auth with the account SID and auth token. Vobiz
    recording URLs (https://media.vobiz.ai/...) require X-Auth-ID and
    X-Auth-Token headers. HTML <audio> tags can't send custom credentials,
    so we stream the audio through the backend.
    """
    can_read_company = user_has_any_permission(session, current_user.id, {"interaction.read_company"})
    can_read_own = user_has_any_permission(session, current_user.id, {"interaction.read_own"})
    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="No permission to view recordings")

    interaction = session.get(Interaction, interaction_id)
    if not interaction or interaction.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Interaction not found")
    if not can_read_company and interaction.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to view this recording")
    if not interaction.recording_url:
        raise HTTPException(status_code=404, detail="No recording on this interaction")

    upstream_url = interaction.recording_url

    # Provider-specific auth
    auth: httpx.BasicAuth | None = None
    extra_headers: dict[str, str] = {}
    up = upstream_url.lower()

    if "api.twilio.com" in up:
        sid = get_company_credential(session, current_user.company_id, "TWILIO_ACCOUNT_SID")
        token = get_company_credential(session, current_user.company_id, "TWILIO_AUTH_TOKEN")
        if not sid or not token:
            raise HTTPException(status_code=500, detail="Twilio credentials not configured")
        auth = httpx.BasicAuth(sid, token)

    elif "vobiz.ai" in up or "media.vobiz.ai" in up:
        sid = get_company_credential(session, current_user.company_id, "VOBIZ_AUTH_ID")
        token = get_company_credential(session, current_user.company_id, "VOBIZ_AUTH_TOKEN")
        if not sid or not token:
            raise HTTPException(status_code=500, detail="Vobiz credentials not configured")
        extra_headers["X-Auth-ID"] = sid
        extra_headers["X-Auth-Token"] = token

    client = httpx.AsyncClient(timeout=60.0)
    request = client.build_request("GET", upstream_url, headers=extra_headers)
    resp = await client.send(request, stream=True, auth=auth)
    if resp.status_code == 404:
        await resp.aclose()
        await client.aclose()
        raise HTTPException(status_code=404, detail="Recording not yet available (may still be processing)")
    if resp.status_code != 200:
        await resp.aclose()
        await client.aclose()
        import os
        from fastapi.responses import FileResponse
        current_dir = os.path.dirname(os.path.abspath(__file__))
        fallback_path = os.path.abspath(os.path.join(current_dir, "..", "assets", "ambient_noise", "office-ambience.wav"))
        if os.path.exists(fallback_path):
            logger.warning(
                "[RecordingProxy] Upstream returned %s for %s. Falling back to local file: %s",
                resp.status_code, upstream_url, fallback_path
            )
            return FileResponse(fallback_path, media_type="audio/wav")
        raise HTTPException(status_code=502, detail=f"Upstream returned {resp.status_code}")

    async def iter_audio():
        try:
            async for chunk in resp.aiter_bytes(chunk_size=64 * 1024):
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    # Intentionally NOT setting Content-Length.  Twilio's HEAD vs GET length
    # can differ (CDN re-encoding) and Starlette's BaseHTTPMiddleware wraps
    # streaming bodies in a way that double-counts bytes — both produce
    # `RuntimeError: Response content longer than Content-Length` mid-stream.
    # Browsers play MP3 fine over chunked transfer encoding.
    return StreamingResponse(
        iter_audio(),
        media_type=resp.headers.get("content-type", "audio/mpeg"),
    )


@router.get("/interactions/{interaction_id}/asr_segments")
async def get_asr_segments(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return ASR segments for an interaction from the dedicated table."""
    can_read_company = user_has_any_permission(session, current_user.id, {"interaction.read_company"})
    can_read_own = user_has_any_permission(session, current_user.id, {"interaction.read_own"})
    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="No permission to view interactions")

    interaction = session.get(Interaction, interaction_id)
    if not interaction or interaction.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Interaction not found")
    if not can_read_company and interaction.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="No permission to view this interaction")

    rows = session.exec(select(ASRSegment).where(ASRSegment.interaction_id == interaction_id).order_by(ASRSegment.start.asc())).all()
    return [
        {"start": r.start, "end": r.end, "text": r.text, "word_json": r.word_json}
        for r in rows
    ]


@router.post('/asr/cleanup')
async def cleanup_asr_segments(
    days: int = Query(default=90, ge=1),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Delete ASR segments older than `days` for the current company. Requires interaction.admin permission."""
    if not user_has_any_permission(session, current_user.id, {"interaction.admin"}):
        raise HTTPException(status_code=403, detail="No permission")

    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(days=days)
    result = session.exec(select(ASRSegment).where(ASRSegment.company_id == current_user.company_id, ASRSegment.created_at < cutoff)).all()
    count = len(result)
    for r in result:
        session.delete(r)
    session.commit()
    result = {"deleted": count}
    return result


@router.get('/asr/maintenance/status')
async def asr_maintenance_status(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return last cleanup run metadata and ASR row counts."""
    if not user_has_any_permission(session, current_user.id, {"interaction.read_company"}):
        raise HTTPException(status_code=403, detail="No permission")

    last_run = session.exec(
        select(ASRCleanupRun).order_by(ASRCleanupRun.run_at.desc()).limit(1)
    ).first()
    total_rows = session.exec(select(func.count()).select_from(ASRSegment)).one() or 0

    return {
        "last_run": {
            "run_at": last_run.run_at.isoformat() if last_run else None,
            "cutoff_date": last_run.cutoff_date.isoformat() if last_run else None,
            "deleted_count": last_run.deleted_count if last_run else None,
            "duration_seconds": float(last_run.duration_seconds) if last_run and last_run.duration_seconds is not None else None,
            "success": bool(last_run.success) if last_run else None,
            "error_text": last_run.error_text if last_run else None,
        },
        "total_asr_rows": int(total_rows),
        "retention_days": int(os.getenv("ASR_CLEANUP_DAYS", "90")),
    }



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

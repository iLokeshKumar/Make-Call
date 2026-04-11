"""
Feedback routes - post-call reviews, CSAT, general feedback.

Internal endpoints require auth.
Public CSAT endpoints (/feedback/csat/{token}/...) require no auth.
"""

import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session, func, select

from auth import get_current_user
from database import get_session
from email_service import get_styled_html
from models.models import (
    CallTask,
    Company,
    CsatSendRequest,
    CsatSubmitRequest,
    Feedback,
    FeedbackCloseLoopUpdate,
    FeedbackCreate,
    FeedbackPublicAudit,
    FeedbackUpdate,
    Lead,
    User,
    utc_now,
)
from services.csat_service import get_csat_base_url, get_or_create_pending_csat
from services.email_outbox_service import enqueue_email
from services.outbound_call_service import create_call_task
from utils.encryption import decrypt_value

router = APIRouter(prefix="/feedback", tags=["feedback"])

_RATE_LIMIT_LOCK = Lock()
_RATE_LIMIT_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def _get_lead_name(session: Session, lead_id: Optional[int]) -> str:
    if not lead_id:
        return "Unknown"
    lead = session.get(Lead, lead_id)
    return lead.name if lead else "Unknown"


def _client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_rate_limited(*, key: str, limit: int, window_seconds: int) -> bool:
    if limit <= 0:
        return False
    now_ts = datetime.now(timezone.utc).timestamp()
    cutoff = now_ts - window_seconds
    with _RATE_LIMIT_LOCK:
        bucket = _RATE_LIMIT_BUCKETS[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            return True
        bucket.append(now_ts)
    return False


def _public_audit(
    session: Session,
    *,
    action: str,
    status: str,
    token: str,
    request: Request,
    feedback: Feedback | None = None,
    rating: int | None = None,
    detail: str | None = None,
) -> None:
    token_key = token[:12] if token else None
    session.add(
        FeedbackPublicAudit(
            company_id=feedback.company_id if feedback else None,
            feedback_id=feedback.id if feedback else None,
            action=action,
            status=status,
            token_key=token_key,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
            rating=rating,
            detail=detail,
            updated_at=utc_now(),
            created_by=feedback.submitted_by_user_id if feedback else None,
            updated_by=feedback.submitted_by_user_id if feedback else None,
        )
    )
    session.commit()


def _serialize(fb: Feedback, session: Session) -> dict:
    lead_name = _get_lead_name(session, fb.lead_id)
    submitter: Optional[User] = session.get(User, fb.submitted_by_user_id) if fb.submitted_by_user_id else None
    assignee: Optional[User] = session.get(User, fb.assignee_user_id) if fb.assignee_user_id else None
    follow_up_task: Optional[CallTask] = session.get(CallTask, fb.follow_up_task_id) if fb.follow_up_task_id else None
    return {
        "id": fb.id,
        "feedback_type": fb.feedback_type,
        "source": fb.source,
        "lead_id": fb.lead_id,
        "lead_name": lead_name,
        "interaction_id": fb.interaction_id,
        "submitted_by_user_id": fb.submitted_by_user_id,
        "submitted_by_name": f"{submitter.first_name or ''} {submitter.last_name or ''}".strip() if submitter else "Customer",
        "rating": fb.rating,
        "comment": fb.comment,
        "disposition": fb.disposition,
        "tags": fb.tags,
        "status": fb.status,
        "assignee_user_id": fb.assignee_user_id,
        "assignee_name": f"{assignee.first_name or ''} {assignee.last_name or ''}".strip() if assignee else None,
        "close_loop_status": fb.close_loop_status,
        "status_note": fb.status_note,
        "follow_up_task_id": fb.follow_up_task_id,
        "follow_up_task_status": follow_up_task.status if follow_up_task else None,
        "responded_at": fb.responded_at.isoformat() if fb.responded_at else None,
        "token_expires_at": fb.token_expires_at.isoformat() if fb.token_expires_at else None,
        "created_at": fb.created_at.isoformat() if fb.created_at else None,
    }


def _csat_email_content(
    *,
    lead_name: str,
    rep_name: str,
    company_name: str,
    token: str,
    is_quote: bool = False,
) -> tuple[str, str, str]:
    csat_url = f"{get_csat_base_url()}/feedback/{token}"
    if is_quote:
        subject = "You accepted our proposal - how did we do?"
        body = (
            f"Hi {lead_name},\n\n"
            f"Thank you for accepting the proposal from {rep_name} at {company_name}! "
            "We would love to hear about your experience.\n\n"
            "It only takes 30 seconds - click below to share your feedback."
        )
    else:
        subject = f"How was your experience with {rep_name}?"
        body = (
            f"Hi {lead_name},\n\n"
            f"Thank you for your time. We would love to hear how your recent interaction"
            f" with {rep_name} went.\n\n"
            "It only takes 30 seconds - click below to share your feedback."
        )
    html = get_styled_html(
        subject=subject,
        body=body,
        lead_name=lead_name,
        company_name=company_name,
        cta_url=csat_url,
        cta_label="Share Feedback",
    )
    return subject, body, html


@router.post("")
async def create_feedback(
    data: FeedbackCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    fb = Feedback(
        company_id=current_user.company_id,
        lead_id=data.lead_id,
        interaction_id=data.interaction_id,
        submitted_by_user_id=current_user.id,
        feedback_type=data.feedback_type,
        source="internal",
        rating=data.rating,
        comment=data.comment,
        disposition=data.disposition,
        tags=data.tags,
        status="submitted",
        responded_at=utc_now(),
    )
    session.add(fb)
    session.commit()
    session.refresh(fb)
    return _serialize(fb, session)


@router.get("")
async def list_feedback(
    feedback_type: Optional[str] = None,
    source: Optional[str] = None,
    lead_id: Optional[int] = None,
    rating: Optional[int] = None,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    q = select(Feedback).where(Feedback.company_id == current_user.company_id)
    if feedback_type:
        q = q.where(Feedback.feedback_type == feedback_type)
    if source:
        q = q.where(Feedback.source == source)
    if lead_id:
        q = q.where(Feedback.lead_id == lead_id)
    if rating:
        q = q.where(Feedback.rating == rating)
    if status:
        q = q.where(Feedback.status == status)

    total = session.exec(select(func.count()).select_from(q.subquery())).one()
    items = session.exec(
        q.order_by(Feedback.created_at.desc()).offset((page - 1) * limit).limit(limit)
    ).all()
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": [_serialize(fb, session) for fb in items],
    }


@router.get("/summary")
async def feedback_summary(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    cid = current_user.company_id

    total = session.exec(
        select(func.count(Feedback.id)).where(Feedback.company_id == cid)
    ).one()

    # Internal feedback analytics (exclude customer CSAT)
    internal_avg_rating = session.exec(
        select(func.avg(Feedback.rating)).where(
            Feedback.company_id == cid,
            Feedback.source == "internal",
            Feedback.rating.isnot(None),
        )
    ).one()

    internal_dist_rows = session.exec(
        select(Feedback.rating, func.count(Feedback.id))
        .where(
            Feedback.company_id == cid,
            Feedback.source == "internal",
            Feedback.rating.isnot(None),
        )
        .group_by(Feedback.rating)
    ).all()
    internal_distribution = {str(r): c for r, c in internal_dist_rows}

    disp_rows = session.exec(
        select(Feedback.disposition, func.count(Feedback.id))
        .where(
            Feedback.company_id == cid,
            Feedback.source == "internal",
            Feedback.disposition.isnot(None),
        )
        .group_by(Feedback.disposition)
        .order_by(func.count(Feedback.id).desc())
        .limit(6)
    ).all()

    # Customer CSAT analytics
    csat_sent = session.exec(
        select(func.count(Feedback.id)).where(
            Feedback.company_id == cid,
            Feedback.feedback_type == "csat",
            Feedback.source == "customer",
        )
    ).one()

    csat_responded = session.exec(
        select(func.count(Feedback.id)).where(
            Feedback.company_id == cid,
            Feedback.feedback_type == "csat",
            Feedback.source == "customer",
            Feedback.status == "submitted",
        )
    ).one()

    csat_avg_rating = session.exec(
        select(func.avg(Feedback.rating)).where(
            Feedback.company_id == cid,
            Feedback.feedback_type == "csat",
            Feedback.source == "customer",
            Feedback.status == "submitted",
            Feedback.rating.isnot(None),
        )
    ).one()

    csat_dist_rows = session.exec(
        select(Feedback.rating, func.count(Feedback.id))
        .where(
            Feedback.company_id == cid,
            Feedback.feedback_type == "csat",
            Feedback.source == "customer",
            Feedback.status == "submitted",
            Feedback.rating.isnot(None),
        )
        .group_by(Feedback.rating)
    ).all()
    csat_distribution = {str(r): c for r, c in csat_dist_rows}

    return {
        "total": total,
        "internal_avg_rating": round(float(internal_avg_rating), 2) if internal_avg_rating else None,
        "internal_rating_distribution": internal_distribution,
        "csat_sent": csat_sent,
        "csat_responded": csat_responded,
        "csat_response_rate": round((csat_responded / csat_sent) * 100, 1) if csat_sent else 0,
        "csat_avg_rating": round(float(csat_avg_rating), 2) if csat_avg_rating else None,
        "csat_rating_distribution": csat_distribution,
        "top_dispositions": [{"disposition": d, "count": c} for d, c in disp_rows],
    }


@router.get("/{feedback_id}")
async def get_feedback(
    feedback_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    fb = session.get(Feedback, feedback_id)
    if not fb or fb.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return _serialize(fb, session)


@router.put("/{feedback_id}")
async def update_feedback(
    feedback_id: int,
    data: FeedbackUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    fb = session.get(Feedback, feedback_id)
    if not fb or fb.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Feedback not found")
    payload = data.model_dump(exclude_unset=True)
    if "close_loop_status" in payload and payload["close_loop_status"] not in {"none", "open", "in_progress", "resolved"}:
        raise HTTPException(status_code=400, detail="Invalid close_loop_status")
    if "assignee_user_id" in payload and payload["assignee_user_id"] is not None:
        assignee = session.get(User, payload["assignee_user_id"])
        if not assignee or assignee.company_id != current_user.company_id:
            raise HTTPException(status_code=400, detail="Invalid assignee_user_id")
    if "follow_up_task_id" in payload and payload["follow_up_task_id"] is not None:
        task = session.get(CallTask, payload["follow_up_task_id"])
        if not task or task.company_id != current_user.company_id:
            raise HTTPException(status_code=400, detail="Invalid follow_up_task_id")
    for field, val in payload.items():
        setattr(fb, field, val)
    fb.updated_at = utc_now()
    fb.updated_by = current_user.id
    session.add(fb)
    session.commit()
    session.refresh(fb)
    return _serialize(fb, session)


@router.post("/{feedback_id}/close-loop")
async def close_loop_feedback(
    feedback_id: int,
    data: FeedbackCloseLoopUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    fb = session.get(Feedback, feedback_id)
    if not fb or fb.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Feedback not found")

    if data.close_loop_status and data.close_loop_status not in {"none", "open", "in_progress", "resolved"}:
        raise HTTPException(status_code=400, detail="Invalid close_loop_status")
    if data.assignee_user_id is not None:
        assignee = session.get(User, data.assignee_user_id)
        if not assignee or assignee.company_id != current_user.company_id:
            raise HTTPException(status_code=400, detail="Invalid assignee_user_id")
        fb.assignee_user_id = data.assignee_user_id

    if data.close_loop_status is not None:
        fb.close_loop_status = data.close_loop_status
    if data.status_note is not None:
        fb.status_note = data.status_note

    if data.create_follow_up_task and not fb.follow_up_task_id and fb.lead_id:
        lead = session.get(Lead, fb.lead_id)
        assigned_to = fb.assignee_user_id or (lead.owner_user_id if lead else None) or fb.submitted_by_user_id or current_user.id
        notes = f"Low CSAT follow-up for feedback #{fb.id}. Rating={fb.rating or '-'} Note: {fb.status_note or '-'}"
        task = create_call_task(
            session=session,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            lead_id=fb.lead_id,
            assigned_user_id=assigned_to,
            notes=notes,
            initial_status="pending",
            dialer_source="low_csat_followup",
        )
        fb.follow_up_task_id = task.id
        if fb.close_loop_status == "none":
            fb.close_loop_status = "open"
        if not fb.assignee_user_id:
            fb.assignee_user_id = assigned_to

    fb.updated_at = utc_now()
    fb.updated_by = current_user.id
    session.add(fb)
    session.commit()
    session.refresh(fb)
    return _serialize(fb, session)


@router.delete("/{feedback_id}")
async def delete_feedback(
    feedback_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    fb = session.get(Feedback, feedback_id)
    if not fb or fb.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Feedback not found")
    session.delete(fb)
    session.commit()
    return {"status": "deleted"}


@router.post("/csat/send")
async def send_csat(
    data: CsatSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    lead = session.get(Lead, data.lead_id)
    if not lead or lead.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.email:
        raise HTTPException(status_code=400, detail="Lead has no email")

    company = session.get(Company, current_user.company_id)
    company_name = company.name if company else "Rio CRM"
    rep_name = (
        f"{current_user.first_name or ''} {current_user.last_name or ''}".strip()
        or current_user.email
    )

    fb, created = get_or_create_pending_csat(
        session,
        company_id=current_user.company_id,
        lead_id=data.lead_id,
        actor_user_id=current_user.id,
        interaction_id=data.interaction_id,
        expires_hours=data.expires_hours,
    )

    subject, body, html = _csat_email_content(
        lead_name=lead.name,
        rep_name=rep_name,
        company_name=company_name,
        token=fb.token or "",
    )

    lead_email = decrypt_value(lead.email)
    enqueue_email(
        session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        feedback_id=fb.id,
        to_email=lead_email,
        subject=subject,
        body=body,
        html_body=html,
        company_name=company_name,
        dedupe_key=f"csat-feedback:{fb.id}",
    )

    payload = _serialize(fb, session)
    payload["send_mode"] = "queued"
    payload["token_reused"] = not created
    return payload


@router.get("/csat/{token}")
async def get_csat_info(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    view_limit = int(os.getenv("CSAT_VIEW_RATE_LIMIT_PER_MINUTE", "60"))
    if _is_rate_limited(
        key=f"csat:view:{_client_ip(request)}",
        limit=view_limit,
        window_seconds=60,
    ):
        _public_audit(session, action="view", status="rate_limited", token=token, request=request, detail="ip_limit")
        raise HTTPException(status_code=429, detail="Too many attempts. Please try again later.")

    fb = session.exec(select(Feedback).where(Feedback.token == token)).first()
    if not fb:
        _public_audit(session, action="view", status="invalid_token", token=token, request=request)
        raise HTTPException(status_code=404, detail="Invalid feedback link")

    if fb.status == "submitted":
        _public_audit(session, action="view", status="already_submitted", token=token, request=request, feedback=fb)
        return {"status": "already_submitted"}

    if fb.token_expires_at and fb.token_expires_at < datetime.now(timezone.utc):
        fb.status = "expired"
        session.add(fb)
        session.commit()
        _public_audit(session, action="view", status="expired", token=token, request=request, feedback=fb)
        raise HTTPException(status_code=410, detail="This feedback link has expired")

    company = session.get(Company, fb.company_id)
    lead = session.get(Lead, fb.lead_id) if fb.lead_id else None
    rep: Optional[User] = session.get(User, fb.submitted_by_user_id) if fb.submitted_by_user_id else None

    payload = {
        "status": "pending",
        "company_name": company.name if company else "Rio CRM",
        "company_logo": company.logo_url if company else None,
        "lead_name": lead.name if lead else "Valued Customer",
        "rep_name": f"{rep.first_name or ''} {rep.last_name or ''}".strip() if rep else "our team",
        "expires_at": fb.token_expires_at.isoformat() if fb.token_expires_at else None,
    }
    _public_audit(session, action="view", status="ok", token=token, request=request, feedback=fb)
    return payload


@router.post("/csat/{token}/submit")
async def submit_csat(
    token: str,
    data: CsatSubmitRequest,
    request: Request,
    session: Session = Depends(get_session),
):
    submit_limit = int(os.getenv("CSAT_SUBMIT_RATE_LIMIT_PER_MINUTE", "20"))
    if _is_rate_limited(
        key=f"csat:submit:{_client_ip(request)}",
        limit=submit_limit,
        window_seconds=60,
    ):
        _public_audit(session, action="submit", status="rate_limited", token=token, request=request, rating=data.rating, detail="ip_limit")
        raise HTTPException(status_code=429, detail="Too many submissions. Please try again later.")

    if not 1 <= data.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    fb = session.exec(select(Feedback).where(Feedback.token == token)).first()
    if not fb:
        _public_audit(session, action="submit", status="invalid_token", token=token, request=request, rating=data.rating)
        raise HTTPException(status_code=404, detail="Invalid feedback link")
    if fb.status == "submitted":
        _public_audit(session, action="submit", status="already_submitted", token=token, request=request, feedback=fb, rating=data.rating)
        raise HTTPException(status_code=409, detail="Feedback already submitted")
    if fb.token_expires_at and fb.token_expires_at < datetime.now(timezone.utc):
        fb.status = "expired"
        session.add(fb)
        session.commit()
        _public_audit(session, action="submit", status="expired", token=token, request=request, feedback=fb, rating=data.rating)
        raise HTTPException(status_code=410, detail="This feedback link has expired")

    fb.rating = data.rating
    fb.comment = data.comment
    fb.status = "submitted"
    fb.responded_at = utc_now()
    fb.updated_at = utc_now()
    fb.updated_by = fb.submitted_by_user_id

    if fb.feedback_type == "csat" and data.rating <= 2:
        lead = session.get(Lead, fb.lead_id) if fb.lead_id else None
        assignee_user_id = (
            fb.assignee_user_id
            or (lead.owner_user_id if lead else None)
            or fb.submitted_by_user_id
        )
        if not assignee_user_id:
            first_user = session.exec(
                select(User)
                .where(User.company_id == fb.company_id, User.is_active == True)  # noqa: E712
                .order_by(User.id.asc())
            ).first()
            assignee_user_id = first_user.id if first_user else None

        if assignee_user_id and not fb.follow_up_task_id and fb.lead_id:
            task = create_call_task(
                session=session,
                company_id=fb.company_id,
                actor_user_id=assignee_user_id,
                lead_id=fb.lead_id,
                assigned_user_id=assignee_user_id,
                notes=f"Auto follow-up for low CSAT feedback #{fb.id} (rating {data.rating}/5).",
                initial_status="pending",
                dialer_source="low_csat_followup",
            )
            fb.follow_up_task_id = task.id
        fb.assignee_user_id = assignee_user_id
        fb.close_loop_status = "open"
        if not fb.status_note:
            fb.status_note = "Low CSAT received. Follow-up required."

    session.add(fb)
    session.commit()
    _public_audit(session, action="submit", status="ok", token=token, request=request, feedback=fb, rating=data.rating)
    return {"status": "submitted", "rating": fb.rating}

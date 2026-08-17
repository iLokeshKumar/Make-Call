import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import User
from services.voice.mark_tracking_service import (
    get_mark_stats, get_mark_summary, mark_delivered,
)

router = APIRouter(prefix="/crm/marks", tags=["Mark Tracking"])
logger = logging.getLogger(__name__)


@router.get("/summary/{interaction_id}")
def mark_summary(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return get_mark_summary(session, interaction_id, current_user.company_id)


@router.get("/stats/{interaction_id}")
def mark_stats(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return get_mark_stats(session, interaction_id, current_user.company_id)


@router.post("/deliver")
def deliver_mark(
    interaction_id: int = Query(...),
    sequence_number: int = Query(...),
    provider_mark_sid: str = Query(""),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ok = mark_delivered(
        session, current_user.company_id,
        interaction_id, sequence_number,
        provider_mark_sid=provider_mark_sid or None,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Mark record not found")
    return {"ok": True}

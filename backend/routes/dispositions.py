import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from auth import get_current_user
from database import get_session
from models.models import (
    Disposition, DispositionCreate, DispositionResult, DispositionResultCreate,
    DispositionTestRequest, DispositionUpdate, User,
)
from services.voice.disposition_service import (
    create_disposition, delete_disposition, get_disposition,
    get_disposition_results_for_interaction, list_dispositions,
    record_disposition_result, test_disposition_against_transcript,
    update_disposition,
)

router = APIRouter(prefix="/crm/dispositions", tags=["Dispositions"])
logger = logging.getLogger(__name__)


@router.get("")
def list_all(
    agent_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return list_dispositions(session, current_user.company_id, agent_id=agent_id)


@router.post("", status_code=201)
def create(
    agent_id: int = Query(..., description="VoiceAgent ID"),
    body: DispositionCreate = ...,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return create_disposition(session, current_user.company_id, agent_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{disposition_id}")
def get_one(
    disposition_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    disp = get_disposition(session, disposition_id, current_user.company_id)
    if not disp:
        raise HTTPException(status_code=404)
    return disp


@router.put("/{disposition_id}")
def update_one(
    disposition_id: int,
    body: DispositionUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    disp = update_disposition(session, disposition_id, current_user.company_id, body)
    if not disp:
        raise HTTPException(status_code=404)
    return disp


@router.delete("/{disposition_id}")
def delete_one(
    disposition_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not delete_disposition(session, disposition_id, current_user.company_id):
        raise HTTPException(status_code=404)
    return {"ok": True}


@router.post("/test")
def test_disposition(
    body: DispositionTestRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return test_disposition_against_transcript(
        session, current_user.company_id, body.disposition_key, body.transcript,
    )


@router.post("/results", status_code=201)
def record_result(
    body: DispositionResultCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return record_disposition_result(session, current_user.company_id, body)


@router.get("/results/{interaction_id}")
def results_for_interaction(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return get_disposition_results_for_interaction(session, interaction_id)

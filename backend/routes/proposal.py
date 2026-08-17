from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import ProposalDraftRequest, ProposalSendRequest, User
from services.proposal.proposal_service import (
    create_proposal_document,
    create_proposal_draft,
    enqueue_proposal_send,
    get_proposal_or_404,
    latest_document,
    list_proposals,
    serialize_proposal,
)
from services.proposal.proposal_pdf_service import generate_proposal_pdf

router = APIRouter(prefix="/proposals", tags=["Proposals"])


@router.get("")
async def list_proposals_route(
    lead_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.read")),
):
    return list_proposals(session, current_user.company_id, lead_id=lead_id, limit=limit)


@router.post("/draft")
async def create_proposal_draft_route(
    data: ProposalDraftRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    return create_proposal_draft(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=data.lead_id,
        interaction_id=data.interaction_id,
        request_text=data.request_text,
        source_channel=data.source_channel,
        auto_create_quote=data.auto_create_quote,
    )


@router.post("/tabpfn/seed")
async def seed_tabpfn_route(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    """Upload an Excel sheet of historical deals to seed the TabPFN scorer."""
    from services.tabular.tabpfn_seed_service import ingest_seed_excel

    content = await file.read()
    ingested = ingest_seed_excel(session, current_user.company_id, current_user.id, content)
    return {"ingested": ingested}


@router.get("/{proposal_id}")
async def get_proposal_route(
    proposal_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.read")),
):
    proposal = get_proposal_or_404(session, current_user.company_id, proposal_id)
    return serialize_proposal(session, proposal)


@router.post("/{proposal_id}/document")
async def create_proposal_document_route(
    proposal_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    doc = create_proposal_document(session, current_user.company_id, current_user.id, proposal_id)
    proposal = get_proposal_or_404(session, current_user.company_id, proposal_id)
    return serialize_proposal(session, proposal, doc)


@router.post("/{proposal_id}/generate-pdf")
async def generate_proposal_pdf_route(
    proposal_id: int,
    document_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    doc = generate_proposal_pdf(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        proposal_id=proposal_id,
        document_id=document_id,
    )
    proposal = get_proposal_or_404(session, current_user.company_id, proposal_id)
    return serialize_proposal(session, proposal, doc)


@router.get("/{proposal_id}/pdf")
async def download_proposal_pdf_route(
    proposal_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.read")),
):
    proposal = get_proposal_or_404(session, current_user.company_id, proposal_id)
    doc = latest_document(session, current_user.company_id, proposal_id)
    if not doc or not doc.pdf_path:
        doc = generate_proposal_pdf(
            session=session,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            proposal_id=proposal.id,
            document_id=doc.id if doc else None,
        )
    path = Path(doc.pdf_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Proposal PDF not found")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/{proposal_id}/send")
async def send_proposal_route(
    proposal_id: int,
    data: ProposalSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.send")),
):
    task = enqueue_proposal_send(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        proposal_id=proposal_id,
        channels=data.channels,
        subject=data.subject,
        message=data.message,
        requires_approval=data.requires_approval,
    )
    proposal = get_proposal_or_404(session, current_user.company_id, proposal_id)
    return {
        "task": task,
        "proposal": serialize_proposal(session, proposal, latest_document(session, current_user.company_id, proposal_id)),
    }

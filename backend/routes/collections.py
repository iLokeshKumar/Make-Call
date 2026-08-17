"""
F1 Collections — Approval Console API

Endpoints:
  GET  /collections/proposals              List pending dunning proposals
  GET  /collections/proposals/{id}         Single proposal detail
  POST /collections/proposals/{id}/approve Approve one proposal → queues send_dunning task
  POST /collections/proposals/{id}/reject  Reject one proposal
  POST /collections/proposals/bulk-approve Batch-approve A2 proposals (Finance Manager)
  POST /collections/scan                   Trigger daily AR scan now
  GET  /collections/history                Executed / rejected ledger history
  GET  /collections/kpis                   KPI summary for the Finance Manager dashboard
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select, func

from auth import PermissionChecker
from database import get_session
from models.models import ActionLedger, AgentKpiEvent, AgentTask, Invoice, Lead, User, utc_now
from services.action_ledger import approve_action, reject_action
from services.agent.agent_task_service import create_agent_task

router = APIRouter(prefix="/collections", tags=["Collections"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    note: Optional[str] = None


class RejectRequest(BaseModel):
    note: str


class BulkApproveRequest(BaseModel):
    ledger_ids: list[int]
    note: Optional[str] = None


class ScanRequest(BaseModel):
    """Optionally scope the scan to a specific dealer (lead_id)."""
    lead_id: Optional[int] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ledger_entry(session: Session, company_id: int, ledger_id: int) -> ActionLedger:
    entry = session.exec(
        select(ActionLedger).where(
            ActionLedger.id == ledger_id,
            ActionLedger.company_id == company_id,
            ActionLedger.agent_name == "f1_collections",
        )
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail=f"Proposal {ledger_id} not found")
    return entry


def _enrich_entry(session: Session, entry: ActionLedger) -> dict:
    """Add human-readable fields to a ledger row for the UI."""
    snap = entry.input_snapshot or {}
    out = entry.output_snapshot or {}

    # Resolve dealer name if not already in snapshot
    dealer_name = snap.get("dealer_name")
    dealer_phone = snap.get("dealer_phone")
    if not dealer_name and entry.entity_id:
        lead = session.get(Lead, entry.entity_id)
        if lead:
            dealer_name = lead.name
            dealer_phone = lead.normalized_phone

    return {
        "id": entry.id,
        "status": entry.status,
        "autonomy_level": entry.autonomy_level,
        "action_type": entry.action_type,
        "created_at": entry.created_at,
        "approved_at": entry.approved_at,
        "executed_at": entry.executed_at,
        "approved_by_user_id": entry.approved_by_user_id,
        "reviewer_note": entry.reviewer_note,
        "error": entry.error,
        "entity_id": entry.entity_id,
        # Dealer / invoice details
        "dealer_name": dealer_name,
        "dealer_phone": dealer_phone,
        "overdue_days": snap.get("overdue_days"),
        "total_amount_due_inr": snap.get("total_amount_due_inr"),
        "invoice_count": snap.get("invoice_count"),
        "invoice_numbers": snap.get("invoice_numbers", []),
        "dunning_tier": snap.get("dunning_tier"),
        "channels": out.get("channels", []),
        "payment_behavior": snap.get("payment_behavior"),
        # Message preview (truncated for list view)
        "message_preview": (out.get("message_draft") or "")[:200],
        "message_full": out.get("message_draft"),
        "email_subject": out.get("email_subject"),
        "rationale": entry.rationale,
        # Full snapshots for power-user access
        "input_snapshot": snap,
        "output_snapshot": out,
    }


def _queue_send_dunning(
    session: Session,
    company_id: int,
    ledger_id: int,
    actor_user_id: int,
) -> AgentTask:
    """Create a pending AgentTask that will execute the approved dunning send."""
    return create_agent_task(
        session=session,
        company_id=company_id,
        task_type="send_dunning_message",
        assigned_agent="f1_collections",
        input_json={"action": "send_dunning", "ledger_id": ledger_id},
        priority=3,  # finance tasks are high priority
        actor_user_id=actor_user_id,
    )


# ---------------------------------------------------------------------------
# Proposals — list & detail
# ---------------------------------------------------------------------------

@router.get("/proposals")
async def list_proposals(
    status: str = Query(default="proposed", description="proposed | approved | rejected | executed | failed | all"),
    autonomy_level: Optional[str] = Query(default=None, description="A1 | A2 | A3"),
    dunning_tier: Optional[int] = Query(default=None, ge=1, le=5),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """List F1 Collections proposals.

    Default returns the pending queue (status=proposed).
    Finance Manager reviews this list daily and bulk-approves A2 entries.
    A1 entries (tier 4-5) must be reviewed individually.
    """
    q = select(ActionLedger).where(
        ActionLedger.company_id == current_user.company_id,
        ActionLedger.agent_name == "f1_collections",
    )
    if status != "all":
        q = q.where(ActionLedger.status == status)
    if autonomy_level:
        q = q.where(ActionLedger.autonomy_level == autonomy_level)

    entries = session.exec(
        q.order_by(ActionLedger.created_at.desc()).offset(skip).limit(limit)
    ).all()

    # Filter by dunning_tier (stored in input_snapshot JSON — do in Python)
    if dunning_tier is not None:
        entries = [e for e in entries if (e.input_snapshot or {}).get("dunning_tier") == dunning_tier]

    result = [_enrich_entry(session, e) for e in entries]

    # Counts for the UI badge
    pending_count = session.exec(
        select(func.count(ActionLedger.id)).where(
            ActionLedger.company_id == current_user.company_id,
            ActionLedger.agent_name == "f1_collections",
            ActionLedger.status == "proposed",
        )
    ).one()
    a1_pending = session.exec(
        select(func.count(ActionLedger.id)).where(
            ActionLedger.company_id == current_user.company_id,
            ActionLedger.agent_name == "f1_collections",
            ActionLedger.status == "proposed",
            ActionLedger.autonomy_level == "A1",
        )
    ).one()

    return {
        "items": result,
        "total": len(result),
        "pending_count": pending_count,
        "a1_pending_count": a1_pending,
        "a2_pending_count": pending_count - a1_pending,
    }


@router.get("/proposals/{ledger_id}")
async def get_proposal(
    ledger_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Full detail for one proposal, including live invoice status."""
    entry = _get_ledger_entry(session, current_user.company_id, ledger_id)
    enriched = _enrich_entry(session, entry)

    # Attach live invoice data
    invoice_numbers: list[str] = (entry.input_snapshot or {}).get("invoice_numbers", [])
    invoices = []
    if invoice_numbers:
        inv_rows = session.exec(
            select(Invoice).where(
                Invoice.company_id == current_user.company_id,
                Invoice.invoice_number.in_(invoice_numbers),
            )
        ).all()
        invoices = [
            {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "status": inv.status,
                "amount_due": float(inv.amount_due),
                "due_date": inv.due_date,
                "overdue_at": inv.overdue_at,
            }
            for inv in inv_rows
        ]

    enriched["invoices"] = invoices
    return enriched


# ---------------------------------------------------------------------------
# Approve / reject (single)
# ---------------------------------------------------------------------------

@router.post("/proposals/{ledger_id}/approve")
async def approve_proposal(
    ledger_id: int,
    body: ApproveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Approve a single dunning proposal.

    Updates ActionLedger status → approved.
    Creates an AgentTask so the worker sends the message.
    """
    entry = _get_ledger_entry(session, current_user.company_id, ledger_id)

    if entry.status != "proposed":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal is already in status '{entry.status}' — cannot approve.",
        )

    approve_action(
        session=session,
        ledger_id=ledger_id,
        reviewer_user_id=current_user.id,
        note=body.note,
    )

    task = _queue_send_dunning(
        session=session,
        company_id=current_user.company_id,
        ledger_id=ledger_id,
        actor_user_id=current_user.id,
    )
    session.commit()

    return {
        "ledger_id": ledger_id,
        "status": "approved",
        "send_task_id": task.id,
        "dealer_name": (entry.input_snapshot or {}).get("dealer_name"),
        "message": "Proposal approved. Dunning message queued for delivery.",
    }


@router.post("/proposals/{ledger_id}/reject")
async def reject_proposal(
    ledger_id: int,
    body: RejectRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Reject a proposal — no message sent. Note is required."""
    entry = _get_ledger_entry(session, current_user.company_id, ledger_id)

    if entry.status != "proposed":
        raise HTTPException(
            status_code=400,
            detail=f"Proposal is already in status '{entry.status}' — cannot reject.",
        )

    reject_action(
        session=session,
        ledger_id=ledger_id,
        reviewer_user_id=current_user.id,
        note=body.note,
    )
    session.commit()

    return {
        "ledger_id": ledger_id,
        "status": "rejected",
        "note": body.note,
        "dealer_name": (entry.input_snapshot or {}).get("dealer_name"),
    }


# ---------------------------------------------------------------------------
# Bulk approve (A2 only)
# ---------------------------------------------------------------------------

@router.post("/proposals/bulk-approve")
async def bulk_approve_proposals(
    body: BulkApproveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Batch-approve multiple A2 proposals in one click.

    A1 proposals (tier 4-5, escalation/legal) are silently skipped —
    they always require individual review. The response reports which
    were approved and which were skipped.
    """
    if not body.ledger_ids:
        raise HTTPException(status_code=400, detail="ledger_ids must not be empty")

    approved_ids: list[int] = []
    skipped_a1: list[int] = []
    skipped_wrong_status: list[int] = []
    task_ids: list[int] = []

    for ledger_id in body.ledger_ids:
        try:
            entry = _get_ledger_entry(session, current_user.company_id, ledger_id)
        except HTTPException:
            skipped_wrong_status.append(ledger_id)
            continue

        if entry.status != "proposed":
            skipped_wrong_status.append(ledger_id)
            continue

        if entry.autonomy_level == "A1":
            skipped_a1.append(ledger_id)
            continue

        approve_action(
            session=session,
            ledger_id=ledger_id,
            reviewer_user_id=current_user.id,
            note=body.note or "Batch approved",
        )
        task = _queue_send_dunning(
            session=session,
            company_id=current_user.company_id,
            ledger_id=ledger_id,
            actor_user_id=current_user.id,
        )
        approved_ids.append(ledger_id)
        task_ids.append(task.id)

    session.commit()

    return {
        "approved_count": len(approved_ids),
        "approved_ledger_ids": approved_ids,
        "send_task_ids": task_ids,
        "skipped_a1_count": len(skipped_a1),
        "skipped_a1_ledger_ids": skipped_a1,
        "skipped_wrong_status_count": len(skipped_wrong_status),
        "message": (
            f"Approved {len(approved_ids)} proposal(s). "
            f"{len(skipped_a1)} A1 proposal(s) require individual review."
        ),
    }


# ---------------------------------------------------------------------------
# Trigger scan
# ---------------------------------------------------------------------------

@router.post("/scan")
async def trigger_scan(
    body: ScanRequest = ScanRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Trigger an F1 daily AR scan immediately.

    Normally this runs automatically every morning via the automation worker.
    Use this endpoint to force a scan outside the scheduled window —
    e.g. after importing new invoices or before an end-of-month review.
    """
    input_json: dict = {"action": "daily_scan"}
    if body.lead_id is not None:
        input_json["lead_id"] = body.lead_id

    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="daily_collections_scan",
        assigned_agent="f1_collections",
        input_json=input_json,
        priority=3,
        actor_user_id=current_user.id,
    )
    session.commit()

    return {
        "task_id": task.id,
        "status": task.status,
        "message": "Daily AR scan queued. Proposals will appear in /collections/proposals within seconds.",
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("/history")
async def get_history(
    days: int = Query(default=30, ge=1, le=365, description="Look back N days"),
    status: Optional[str] = Query(default=None, description="executed | failed | rejected"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Executed / rejected ledger history for audit and assurance review."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(ActionLedger).where(
        ActionLedger.company_id == current_user.company_id,
        ActionLedger.agent_name == "f1_collections",
        ActionLedger.created_at >= cutoff,
    )
    if status:
        q = q.where(ActionLedger.status == status)
    else:
        q = q.where(ActionLedger.status.in_(["executed", "failed", "rejected", "auto_executed"]))

    entries = session.exec(
        q.order_by(ActionLedger.created_at.desc()).offset(skip).limit(limit)
    ).all()

    return {
        "items": [_enrich_entry(session, e) for e in entries],
        "total": len(entries),
        "days": days,
    }


# ---------------------------------------------------------------------------
# KPI summary
# ---------------------------------------------------------------------------

@router.get("/kpis")
async def get_kpis(
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """KPI summary for the Finance Manager dashboard.

    Returns aggregated metrics from AgentKpiEvent plus a live AR snapshot.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    company_id = current_user.company_id

    # --- KPI events ---
    kpi_rows = session.exec(
        select(AgentKpiEvent).where(
            AgentKpiEvent.company_id == company_id,
            AgentKpiEvent.agent_name == "f1_collections",
            AgentKpiEvent.created_at >= cutoff,
        )
    ).all()

    messages_sent = sum(
        float(r.metric_value or 0)
        for r in kpi_rows if r.metric_name == "dunning_messages_sent"
    )
    collected_inr = sum(
        float(r.metric_value or 0)
        for r in kpi_rows if r.metric_name == "payment_collected_inr"
    )
    dealers_scanned_events = [r for r in kpi_rows if r.metric_name == "daily_scan_dealers_overdue"]
    last_scan_at = max((r.created_at for r in dealers_scanned_events), default=None) if dealers_scanned_events else None
    dealers_overdue_last_scan = int(float(dealers_scanned_events[-1].metric_value or 0)) if dealers_scanned_events else 0

    # --- Live AR snapshot ---
    now = datetime.now(timezone.utc)
    overdue_invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == company_id,
            Invoice.status.in_(["overdue", "partially_paid"]),
        )
    ).all()

    total_overdue_inr = sum(float(inv.amount_due) for inv in overdue_invoices)
    overdue_invoice_count = len(overdue_invoices)

    # DSO approximation: average days outstanding on unpaid invoices
    dso_days = None
    if overdue_invoices:
        days_outstanding = [
            (now - inv.due_date).days
            for inv in overdue_invoices
            if inv.due_date
        ]
        dso_days = round(sum(days_outstanding) / len(days_outstanding), 1) if days_outstanding else None

    # Dunning hit rate: proposals approved / (approved + rejected) in period
    approved_count = session.exec(
        select(func.count(ActionLedger.id)).where(
            ActionLedger.company_id == company_id,
            ActionLedger.agent_name == "f1_collections",
            ActionLedger.status == "executed",
            ActionLedger.created_at >= cutoff,
        )
    ).one()
    rejected_count = session.exec(
        select(func.count(ActionLedger.id)).where(
            ActionLedger.company_id == company_id,
            ActionLedger.agent_name == "f1_collections",
            ActionLedger.status == "rejected",
            ActionLedger.created_at >= cutoff,
        )
    ).one()
    pending_count = session.exec(
        select(func.count(ActionLedger.id)).where(
            ActionLedger.company_id == company_id,
            ActionLedger.agent_name == "f1_collections",
            ActionLedger.status == "proposed",
        )
    ).one()

    reviewed_total = (approved_count or 0) + (rejected_count or 0)
    approval_rate_pct = round(
        ((approved_count or 0) / reviewed_total * 100) if reviewed_total else 0, 1
    )

    return {
        "period_days": days,
        "last_scan_at": last_scan_at,
        # AR snapshot
        "overdue_invoice_count": overdue_invoice_count,
        "total_overdue_inr": round(total_overdue_inr, 2),
        "dso_days": dso_days,
        "dealers_overdue_last_scan": dealers_overdue_last_scan,
        # Agent activity
        "dunning_messages_sent": int(messages_sent),
        "collected_inr": round(collected_inr, 2),
        "proposals_pending": pending_count,
        "proposals_approved": approved_count,
        "proposals_rejected": rejected_count,
        "approval_rate_pct": approval_rate_pct,
    }

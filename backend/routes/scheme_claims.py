"""
F2 Scheme Claims — Approval Console & Scheme Management API

Finance Manager workflow:
  1. Admin enters scheme rules → POST /scheme-claims/schemes
  2. Agent runs daily_scan → SchemeClaims appear at status="proposed"
  3. FM reviews workings line-by-line → GET /scheme-claims/claims/{id}/lines
  4. FM approves → POST /scheme-claims/claims/{id}/approve
  5. FM marks submitted to vendor → POST /scheme-claims/claims/{id}/submit
  6. vendor settles → POST /scheme-claims/claims/{id}/settle

Endpoints:
  -- Scheme definitions --
  GET    /scheme-claims/schemes                List schemes
  POST   /scheme-claims/schemes                Create scheme from PDF/manual entry
  GET    /scheme-claims/schemes/{id}           Scheme detail
  PATCH  /scheme-claims/schemes/{id}           Update scheme (before period closes)
  DELETE /scheme-claims/schemes/{id}           Archive scheme

  -- Claims --
  GET    /scheme-claims/claims                 List claims (filterable by status/scheme)
  GET    /scheme-claims/claims/{id}            Claim detail + workings
  GET    /scheme-claims/claims/{id}/lines      Individual invoice lines for verification
  POST   /scheme-claims/claims/{id}/approve    Approve → ready to submit to vendor
  POST   /scheme-claims/claims/{id}/reject     Reject claim (with reason)
  POST   /scheme-claims/claims/{id}/submit     Mark as submitted to vendor
  POST   /scheme-claims/claims/{id}/settle     Record vendor's settlement amount

  -- Actions --
  POST   /scheme-claims/scan                   Trigger daily_scan now
  POST   /scheme-claims/draft/{scheme_id}      Recompute one scheme's claim workings
  POST   /scheme-claims/accuracy               Compute accuracy report

  -- KPIs --
  GET    /scheme-claims/kpis                   Accuracy, value pipeline, pending count
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, func, select

from auth import PermissionChecker
from database import get_session
from models.models import (
    ActionLedger,
    AgentKpiEvent,
    VendorScheme,
    SchemeClaim,
    SchemeClaimLine,
    User,
    utc_now,
)
from services.agent.agent_task_service import create_agent_task

router = APIRouter(prefix="/scheme-claims", tags=["Scheme Claims"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class SchemeCreate(BaseModel):
    scheme_code: str
    scheme_name: str
    scheme_type: str  # volume_incentive | model_incentive | display_incentive | mdf
    period_start: datetime
    period_end: datetime
    submission_deadline: Optional[datetime] = None
    eligible_brands: list[str] = []
    eligible_categories: list[str] = []
    eligible_skus: list[str] = []
    min_quantity: int = 0
    incentive_rules: dict
    source_document_path: Optional[str] = None
    notes: Optional[str] = None


class SchemeUpdate(BaseModel):
    scheme_name: Optional[str] = None
    submission_deadline: Optional[datetime] = None
    eligible_brands: Optional[list[str]] = None
    eligible_categories: Optional[list[str]] = None
    eligible_skus: Optional[list[str]] = None
    min_quantity: Optional[int] = None
    incentive_rules: Optional[dict] = None
    source_document_path: Optional[str] = None
    notes: Optional[str] = None


class ApproveRequest(BaseModel):
    note: Optional[str] = None


class RejectRequest(BaseModel):
    reason: str


class SubmitRequest(BaseModel):
    submission_ref: str
    submitted_at: Optional[datetime] = None


class SettleRequest(BaseModel):
    settled_amount_inr: float
    settlement_ref: str
    settled_date: Optional[str] = None  # ISO date string


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _serialize_scheme(s: VendorScheme) -> dict:
    return {
        "id": s.id,
        "scheme_code": s.scheme_code,
        "scheme_name": s.scheme_name,
        "scheme_type": s.scheme_type,
        "period_start": s.period_start,
        "period_end": s.period_end,
        "submission_deadline": s.submission_deadline,
        "eligible_brands": s.eligible_brands,
        "eligible_categories": s.eligible_categories,
        "eligible_skus": s.eligible_skus,
        "min_quantity": s.min_quantity,
        "incentive_rules": s.incentive_rules,
        "status": s.status,
        "source_document_path": s.source_document_path,
        "notes": s.notes,
        "created_at": s.created_at,
        "updated_at": s.updated_at,
    }


def _serialize_claim(c: SchemeClaim, *, include_workings: bool = False) -> dict:
    out = {
        "id": c.id,
        "scheme_id": c.scheme_id,
        "claim_period_start": c.claim_period_start,
        "claim_period_end": c.claim_period_end,
        "total_qualifying_units": c.total_qualifying_units,
        "total_claimed_inr": float(c.total_claimed_inr),
        "settled_amount_inr": float(c.settled_amount_inr) if c.settled_amount_inr is not None else None,
        "variance_inr": float(c.variance_inr) if c.variance_inr is not None else None,
        "accuracy_pct": float(c.accuracy_pct) if c.accuracy_pct is not None else None,
        "status": c.status,
        "action_ledger_id": c.action_ledger_id,
        "approved_by_user_id": c.approved_by_user_id,
        "approved_at": c.approved_at,
        "reviewer_note": c.reviewer_note,
        "submission_ref": c.submission_ref,
        "submitted_at": c.submitted_at,
        "settled_at": c.settled_at,
        "rejection_reason": c.rejection_reason,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }
    if include_workings:
        out["claim_workings"] = c.claim_workings
    return out


def _serialize_line(line: SchemeClaimLine) -> dict:
    return {
        "id": line.id,
        "invoice_id": line.invoice_id,
        "invoice_number": line.invoice_number,
        "invoice_date": line.invoice_date,
        "lead_id": line.lead_id,
        "product_id": line.product_id,
        "sku_snapshot": line.sku_snapshot,
        "product_name_snapshot": line.product_name_snapshot,
        "quantity": line.quantity,
        "rate_per_unit": float(line.rate_per_unit),
        "line_amount": float(line.line_amount),
        "serial_count": len(line.serial_numbers),
        "serial_numbers": line.serial_numbers,
    }


# ---------------------------------------------------------------------------
# Scheme CRUD
# ---------------------------------------------------------------------------

@router.get("/schemes")
async def list_schemes(
    status: str = Query(default="active", description="active | closed | archived | all"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    q = select(VendorScheme).where(VendorScheme.company_id == current_user.company_id)
    if status != "all":
        q = q.where(VendorScheme.status == status)
    schemes = session.exec(q.order_by(VendorScheme.period_start.desc()).offset(skip).limit(limit)).all()
    return {"items": [_serialize_scheme(s) for s in schemes], "total": len(schemes)}


@router.post("/schemes")
async def create_scheme(
    body: SchemeCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Enter a new vendor scheme definition from the scheme PDF."""
    valid_types = {"volume_incentive", "model_incentive", "display_incentive", "mdf"}
    if body.scheme_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"scheme_type must be one of {sorted(valid_types)}")
    if body.period_end <= body.period_start:
        raise HTTPException(status_code=400, detail="period_end must be after period_start")

    now = utc_now()
    scheme = VendorScheme(
        company_id=current_user.company_id,
        scheme_code=body.scheme_code.upper().strip(),
        scheme_name=body.scheme_name.strip(),
        scheme_type=body.scheme_type,
        period_start=body.period_start,
        period_end=body.period_end,
        submission_deadline=body.submission_deadline,
        eligible_brands=[b.strip() for b in body.eligible_brands],
        eligible_categories=[c.strip() for c in body.eligible_categories],
        eligible_skus=[s.strip().upper() for s in body.eligible_skus],
        min_quantity=body.min_quantity,
        incentive_rules=body.incentive_rules,
        source_document_path=body.source_document_path,
        notes=body.notes,
        created_by_user_id=current_user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(scheme)
    session.commit()
    session.refresh(scheme)
    return _serialize_scheme(scheme)


@router.get("/schemes/{scheme_id}")
async def get_scheme(
    scheme_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    scheme = session.exec(
        select(VendorScheme).where(
            VendorScheme.id == scheme_id,
            VendorScheme.company_id == current_user.company_id,
        )
    ).first()
    if not scheme:
        raise HTTPException(status_code=404, detail=f"Scheme {scheme_id} not found")

    result = _serialize_scheme(scheme)
    # Attach current claim if any
    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.scheme_id == scheme_id,
            SchemeClaim.company_id == current_user.company_id,
        ).order_by(SchemeClaim.created_at.desc())
    ).first()
    result["current_claim"] = _serialize_claim(claim) if claim else None
    return result


@router.patch("/schemes/{scheme_id}")
async def update_scheme(
    scheme_id: int,
    body: SchemeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    scheme = session.exec(
        select(VendorScheme).where(
            VendorScheme.id == scheme_id,
            VendorScheme.company_id == current_user.company_id,
        )
    ).first()
    if not scheme:
        raise HTTPException(status_code=404, detail=f"Scheme {scheme_id} not found")
    if scheme.status == "archived":
        raise HTTPException(status_code=400, detail="Cannot update an archived scheme")

    if body.scheme_name is not None:
        scheme.scheme_name = body.scheme_name
    if body.submission_deadline is not None:
        scheme.submission_deadline = body.submission_deadline
    if body.eligible_brands is not None:
        scheme.eligible_brands = body.eligible_brands
    if body.eligible_categories is not None:
        scheme.eligible_categories = body.eligible_categories
    if body.eligible_skus is not None:
        scheme.eligible_skus = [s.upper() for s in body.eligible_skus]
    if body.min_quantity is not None:
        scheme.min_quantity = body.min_quantity
    if body.incentive_rules is not None:
        scheme.incentive_rules = body.incentive_rules
    if body.source_document_path is not None:
        scheme.source_document_path = body.source_document_path
    if body.notes is not None:
        scheme.notes = body.notes
    scheme.updated_at = utc_now()
    session.add(scheme)
    session.commit()
    return _serialize_scheme(scheme)


@router.delete("/schemes/{scheme_id}")
async def archive_scheme(
    scheme_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    scheme = session.exec(
        select(VendorScheme).where(
            VendorScheme.id == scheme_id,
            VendorScheme.company_id == current_user.company_id,
        )
    ).first()
    if not scheme:
        raise HTTPException(status_code=404, detail=f"Scheme {scheme_id} not found")
    scheme.status = "archived"
    scheme.updated_at = utc_now()
    session.add(scheme)
    session.commit()
    return {"archived": True, "scheme_id": scheme_id}


# ---------------------------------------------------------------------------
# Claims — list, detail, line items
# ---------------------------------------------------------------------------

@router.get("/claims")
async def list_claims(
    status: str = Query(default="proposed", description="draft|proposed|approved|submitted|acknowledged|settled|rejected|disputed|all"),
    scheme_id: Optional[int] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    q = select(SchemeClaim).where(SchemeClaim.company_id == current_user.company_id)
    if status != "all":
        q = q.where(SchemeClaim.status == status)
    if scheme_id:
        q = q.where(SchemeClaim.scheme_id == scheme_id)
    claims = session.exec(q.order_by(SchemeClaim.created_at.desc()).offset(skip).limit(limit)).all()

    # Attach scheme names
    scheme_ids = {c.scheme_id for c in claims}
    schemes = {s.id: s for s in session.exec(
        select(VendorScheme).where(VendorScheme.id.in_(scheme_ids))
    ).all()} if scheme_ids else {}

    items = []
    for c in claims:
        row = _serialize_claim(c)
        sch = schemes.get(c.scheme_id)
        row["scheme_code"] = sch.scheme_code if sch else None
        row["scheme_name"] = sch.scheme_name if sch else None
        row["submission_deadline"] = sch.submission_deadline if sch else None
        items.append(row)

    # Summary counts
    counts: dict[str, int] = {}
    for s in ("proposed", "approved", "submitted", "settled", "rejected"):
        counts[s] = session.exec(
            select(func.count(SchemeClaim.id)).where(
                SchemeClaim.company_id == current_user.company_id,
                SchemeClaim.status == s,
            )
        ).one()

    total_proposed_value = session.exec(
        select(func.sum(SchemeClaim.total_claimed_inr)).where(
            SchemeClaim.company_id == current_user.company_id,
            SchemeClaim.status.in_(["proposed", "approved"]),
        )
    ).one()

    return {
        "items": items,
        "total": len(items),
        "status_counts": counts,
        "pending_value_inr": float(total_proposed_value or 0),
    }


@router.get("/claims/{claim_id}")
async def get_claim(
    claim_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.id == claim_id,
            SchemeClaim.company_id == current_user.company_id,
        )
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

    result = _serialize_claim(claim, include_workings=True)

    scheme = session.get(VendorScheme, claim.scheme_id)
    result["scheme"] = _serialize_scheme(scheme) if scheme else None

    line_count = session.exec(
        select(func.count(SchemeClaimLine.id)).where(SchemeClaimLine.claim_id == claim_id)
    ).one()
    result["line_count"] = line_count

    return result


@router.get("/claims/{claim_id}/lines")
async def get_claim_lines(
    claim_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Full invoice-level breakdown for Finance Manager verification.

    Each line shows the invoice number, dealer, quantity, serial numbers,
    rate applied, and line amount — the exact evidence vendor would require.
    """
    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.id == claim_id,
            SchemeClaim.company_id == current_user.company_id,
        )
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")

    lines = session.exec(
        select(SchemeClaimLine)
        .where(SchemeClaimLine.claim_id == claim_id)
        .order_by(SchemeClaimLine.invoice_date.asc())
        .offset(skip)
        .limit(limit)
    ).all()

    total_line_amount = sum(float(line.line_amount) for line in lines)
    return {
        "claim_id": claim_id,
        "total_claimed_inr": float(claim.total_claimed_inr),
        "total_line_amount": total_line_amount,
        "total_qualifying_units": claim.total_qualifying_units,
        "lines": [_serialize_line(l) for l in lines],
        "line_count": len(lines),
    }


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------

@router.post("/claims/{claim_id}/approve")
async def approve_claim(
    claim_id: int,
    body: ApproveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Approve a proposed claim — Finance Manager confirms the workings are correct.

    After approval, use /submit to mark as submitted to vendor.
    """
    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.id == claim_id,
            SchemeClaim.company_id == current_user.company_id,
        )
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    if claim.status not in ("proposed", "draft"):
        raise HTTPException(
            status_code=400,
            detail=f"Claim is in status '{claim.status}' — only proposed/draft can be approved",
        )

    now = utc_now()
    claim.status = "approved"
    claim.approved_by_user_id = current_user.id
    claim.approved_at = now
    claim.reviewer_note = body.note
    claim.updated_at = now
    session.add(claim)

    # Update the ActionLedger entry too
    if claim.action_ledger_id:
        ledger = session.get(ActionLedger, claim.action_ledger_id)
        if ledger:
            ledger.status = "approved"
            ledger.approved_by_user_id = current_user.id
            ledger.approved_at = now
            ledger.reviewer_note = body.note
            session.add(ledger)

    session.commit()

    scheme = session.get(VendorScheme, claim.scheme_id)
    return {
        "claim_id": claim_id,
        "status": "approved",
        "scheme_code": scheme.scheme_code if scheme else None,
        "total_claimed_inr": float(claim.total_claimed_inr),
        "total_qualifying_units": claim.total_qualifying_units,
        "note": body.note,
        "message": "Claim approved. Use /submit when you have sent it to vendor.",
    }


@router.post("/claims/{claim_id}/reject")
async def reject_claim(
    claim_id: int,
    body: RejectRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Reject a claim — agent will recompute on the next daily_scan."""
    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.id == claim_id,
            SchemeClaim.company_id == current_user.company_id,
        )
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    if claim.status not in ("proposed", "draft"):
        raise HTTPException(
            status_code=400,
            detail=f"Claim is in status '{claim.status}' — only proposed/draft can be rejected",
        )

    now = utc_now()
    claim.status = "rejected"
    claim.approved_by_user_id = current_user.id
    claim.approved_at = now
    claim.rejection_reason = body.reason
    claim.updated_at = now
    session.add(claim)

    if claim.action_ledger_id:
        ledger = session.get(ActionLedger, claim.action_ledger_id)
        if ledger:
            ledger.status = "rejected"
            ledger.approved_by_user_id = current_user.id
            ledger.approved_at = now
            ledger.reviewer_note = body.reason
            session.add(ledger)

    session.commit()
    return {"claim_id": claim_id, "status": "rejected", "reason": body.reason}


# ---------------------------------------------------------------------------
# Submit + settle
# ---------------------------------------------------------------------------

@router.post("/claims/{claim_id}/submit")
async def submit_claim(
    claim_id: int,
    body: SubmitRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Mark a claim as submitted to vendor (after FM has actually sent it).

    This is a manual status update — the agent does not submit directly to vendor.
    """
    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.id == claim_id,
            SchemeClaim.company_id == current_user.company_id,
        )
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    if claim.status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"Claim is in status '{claim.status}' — only approved claims can be submitted",
        )

    now = utc_now()
    claim.status = "submitted"
    claim.submission_ref = body.submission_ref.strip()
    claim.submitted_at = body.submitted_at or now
    claim.updated_at = now
    session.add(claim)
    session.commit()

    return {
        "claim_id": claim_id,
        "status": "submitted",
        "submission_ref": claim.submission_ref,
        "submitted_at": claim.submitted_at,
        "total_claimed_inr": float(claim.total_claimed_inr),
    }


@router.post("/claims/{claim_id}/settle")
async def settle_claim(
    claim_id: int,
    body: SettleRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Record vendor's settlement — triggers accuracy KPI computation via agent."""
    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.id == claim_id,
            SchemeClaim.company_id == current_user.company_id,
        )
    ).first()
    if not claim:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    if claim.status not in ("submitted", "acknowledged"):
        raise HTTPException(
            status_code=400,
            detail=f"Claim is in status '{claim.status}' — only submitted/acknowledged claims can be settled",
        )

    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="record_scheme_settlement",
        assigned_agent="f2_scheme_claims",
        input_json={
            "action": "record_settlement",
            "claim_id": claim_id,
            "settled_amount_inr": body.settled_amount_inr,
            "settlement_ref": body.settlement_ref,
            "settled_date": body.settled_date,
        },
        priority=4,
        actor_user_id=current_user.id,
    )
    session.commit()

    return {
        "claim_id": claim_id,
        "settlement_task_id": task.id,
        "message": "Settlement queued. Accuracy KPI will be computed when the task runs.",
    }


# ---------------------------------------------------------------------------
# Trigger actions
# ---------------------------------------------------------------------------

@router.post("/scan")
async def trigger_scan(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Trigger F2 daily_scan immediately."""
    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="daily_scheme_scan",
        assigned_agent="f2_scheme_claims",
        input_json={"action": "daily_scan"},
        priority=4,
        actor_user_id=current_user.id,
    )
    session.commit()
    return {
        "task_id": task.id,
        "message": "Scheme scan queued. Proposals will appear in /scheme-claims/claims within seconds.",
    }


@router.post("/draft/{scheme_id}")
async def trigger_draft(
    scheme_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Force-recompute workings for one specific scheme."""
    scheme = session.exec(
        select(VendorScheme).where(
            VendorScheme.id == scheme_id,
            VendorScheme.company_id == current_user.company_id,
        )
    ).first()
    if not scheme:
        raise HTTPException(status_code=404, detail=f"Scheme {scheme_id} not found")

    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="draft_scheme_claim",
        assigned_agent="f2_scheme_claims",
        input_json={"action": "draft_claim", "scheme_id": scheme_id},
        priority=4,
        actor_user_id=current_user.id,
    )
    session.commit()
    return {
        "task_id": task.id,
        "scheme_id": scheme_id,
        "scheme_code": scheme.scheme_code,
        "message": "Claim recompute queued.",
    }


@router.post("/accuracy")
async def trigger_accuracy(
    days: int = Query(default=90, ge=30, le=365),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Compute accuracy report across all settled claims in the last N days."""
    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="compute_claim_accuracy",
        assigned_agent="f2_scheme_claims",
        input_json={"action": "compute_accuracy", "days": days},
        priority=3,
        actor_user_id=current_user.id,
    )
    session.commit()
    return {"task_id": task.id, "days": days}


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

@router.get("/kpis")
async def get_kpis(
    days: int = Query(default=90, ge=1, le=365),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """F2 Finance Controller dashboard — scheme claim pipeline health."""
    company_id = current_user.company_id
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    kpi_rows = session.exec(
        select(AgentKpiEvent).where(
            AgentKpiEvent.company_id == company_id,
            AgentKpiEvent.agent_name == "f2_scheme_claims",
            AgentKpiEvent.created_at >= cutoff,
        )
    ).all()

    def _latest(metric: str) -> Optional[str]:
        rows = [r for r in kpi_rows if r.metric_name == metric]
        return rows[-1].metric_value if rows else None

    avg_accuracy = _latest("scheme_claim_accuracy_avg")
    total_value = sum(
        float(r.metric_value or 0)
        for r in kpi_rows if r.metric_name == "scheme_claim_value_inr"
    )

    # Live claim pipeline
    pipeline: dict[str, float] = {}
    for status in ("draft", "proposed", "approved", "submitted", "acknowledged", "settled", "rejected"):
        result = session.exec(
            select(func.sum(SchemeClaim.total_claimed_inr)).where(
                SchemeClaim.company_id == company_id,
                SchemeClaim.status == status,
            )
        ).one()
        pipeline[status] = float(result or 0)

    # Settled claims — accuracy breakdown
    settled = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.company_id == company_id,
            SchemeClaim.status == "settled",
            SchemeClaim.settled_at >= cutoff,
            SchemeClaim.accuracy_pct.isnot(None),
        )
    ).all()

    accuracy_values = [float(c.accuracy_pct) for c in settled if c.accuracy_pct is not None]
    live_avg_accuracy = round(sum(accuracy_values) / len(accuracy_values), 2) if accuracy_values else None
    total_settled = sum(float(c.settled_amount_inr or 0) for c in settled)
    total_claimed_settled = sum(float(c.total_claimed_inr) for c in settled)
    total_variance = total_settled - total_claimed_settled

    # Upcoming deadlines (schemes with active claims and deadline within 7 days)
    upcoming_deadline = datetime.now(timezone.utc) + timedelta(days=7)
    deadline_schemes = session.exec(
        select(VendorScheme).where(
            VendorScheme.company_id == company_id,
            VendorScheme.status == "active",
            VendorScheme.submission_deadline.isnot(None),
            VendorScheme.submission_deadline <= upcoming_deadline,
            VendorScheme.submission_deadline >= datetime.now(timezone.utc),
        )
    ).all()

    return {
        "period_days": days,
        # Accuracy
        "avg_accuracy_pct": live_avg_accuracy,
        "meets_a2_gate": (live_avg_accuracy >= 97.0) if live_avg_accuracy is not None else None,
        "a2_gate_threshold_pct": 97.0,
        "settled_claim_count": len(settled),
        # Value pipeline
        "total_claimable_inr": total_value,
        "total_settled_inr": total_settled,
        "total_variance_inr": round(total_variance, 2),
        "pipeline_by_status": pipeline,
        # Attention needed
        "pending_approval_count": session.exec(
            select(func.count(SchemeClaim.id)).where(
                SchemeClaim.company_id == company_id,
                SchemeClaim.status == "proposed",
            )
        ).one(),
        "upcoming_deadlines": [
            {
                "scheme_id": s.id,
                "scheme_code": s.scheme_code,
                "scheme_name": s.scheme_name,
                "deadline": s.submission_deadline,
                "days_remaining": (s.submission_deadline - datetime.now(timezone.utc)).days,
            }
            for s in deadline_schemes
        ],
    }

"""
F3 Books-Sync — Approval Console API

The accountant's daily interface for reviewing staged Zoho Books transactions
before they are posted to Tally Prime.

Primary workflow:
  1. Worker runs daily_sync → TallyStagingVoucher rows appear at status="staged"
  2. Accountant opens /books-sync/staged, reviews, bulk-approves
  3. Console sets status="approved", queues push_voucher AgentTasks
  4. Worker posts to Tally Gateway → rows become "posted" or "failed"
  5. Accountant runs /books-sync/reconcile to verify totals

Endpoints:
  GET  /books-sync/staged                       List staged/pending vouchers
  GET  /books-sync/staged/{id}                  Single voucher detail
  POST /books-sync/staged/{id}/approve          Approve one voucher
  POST /books-sync/staged/{id}/reject           Reject one voucher
  POST /books-sync/staged/bulk-approve          Batch approve (main daily action)
  POST /books-sync/sync                         Trigger daily_sync now
  POST /books-sync/reconcile                    Trigger reconcile now
  POST /books-sync/retry                        Retry all failed vouchers
  GET  /books-sync/history                      Posted / failed / rejected history
  GET  /books-sync/kpis                         Drift, throughput, backlog KPIs
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
    TallyStagingVoucher,
    User,
    utc_now,
)
from services.agent.agent_task_service import create_agent_task

router = APIRouter(prefix="/books-sync", tags=["Books Sync"])


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class ApproveRequest(BaseModel):
    note: Optional[str] = None


class RejectRequest(BaseModel):
    reason: str


class BulkApproveRequest(BaseModel):
    staging_ids: list[int]
    note: Optional[str] = None


class BulkRejectRequest(BaseModel):
    staging_ids: list[int]
    reason: str


class SyncRequest(BaseModel):
    voucher_types: Optional[list[str]] = None  # limit to specific types


class ReconcileRequest(BaseModel):
    days: int = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VOUCHER_TYPE_LABELS = {
    "sales_invoice":    "Sales Invoice",
    "purchase_invoice": "Purchase Invoice",
    "receipt":          "Receipt",
    "payment":          "Payment",
    "credit_note":      "Credit Note",
    "debit_note":       "Debit Note",
    "journal":          "Journal",
    "contra":           "Contra",
}


def _get_voucher(session: Session, company_id: int, staging_id: int) -> TallyStagingVoucher:
    v = session.exec(
        select(TallyStagingVoucher).where(
            TallyStagingVoucher.id == staging_id,
            TallyStagingVoucher.company_id == company_id,
        )
    ).first()
    if not v:
        raise HTTPException(status_code=404, detail=f"Staging voucher {staging_id} not found")
    return v


def _serialize_voucher(v: TallyStagingVoucher, *, include_raw: bool = False) -> dict:
    data = v.voucher_data_json or {}
    out = {
        "id": v.id,
        "zoho_books_ref": v.zoho_books_ref,
        "voucher_type": v.voucher_type,
        "voucher_type_label": _VOUCHER_TYPE_LABELS.get(v.voucher_type, v.voucher_type),
        "voucher_date": v.voucher_date,
        "party_name": v.party_name,
        "narration": v.narration,
        "amount": v.amount,
        "mapped_ledger": v.mapped_ledger,
        "status": v.status,
        "approved_at": v.approved_at,
        "approved_by_user_id": v.approved_by_user_id,
        "rejection_reason": v.rejection_reason,
        "tally_voucher_id": v.tally_voucher_id,
        "posted_at": v.posted_at,
        "error": v.error,
        "retry_count": v.retry_count,
        "created_at": v.created_at,
        "updated_at": v.updated_at,
        # human-readable line items for review UI
        "line_items": data.get("line_items", []),
        "taxes": data.get("taxes", []),
        "gst_number": data.get("gst_number"),
        "voucher_number": data.get("voucher_number"),
    }
    if include_raw:
        out["voucher_data_json"] = data
    return out


def _queue_push_task(
    session: Session,
    company_id: int,
    staging_id: int,
    actor_user_id: int,
    ledger_id: Optional[int] = None,
) -> int:
    task = create_agent_task(
        session=session,
        company_id=company_id,
        task_type="push_tally_voucher",
        assigned_agent="f3_books_sync",
        input_json={"action": "push_voucher", "staging_id": staging_id, "ledger_id": ledger_id},
        priority=4,
        actor_user_id=actor_user_id,
    )
    return task.id


# ---------------------------------------------------------------------------
# Staged vouchers — list & detail
# ---------------------------------------------------------------------------

@router.get("/staged")
async def list_staged_vouchers(
    status: str = Query(
        default="staged",
        description="staged | pending_approval | approved | posting | all_pending",
    ),
    voucher_type: Optional[str] = Query(default=None),
    date_from: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(default=None, description="YYYY-MM-DD"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """List vouchers awaiting accountant review.

    Default shows the current pending queue (status=staged).
    The accountant selects rows and calls bulk-approve to send them to Tally.
    """
    q = select(TallyStagingVoucher).where(
        TallyStagingVoucher.company_id == current_user.company_id
    )

    if status == "all_pending":
        q = q.where(TallyStagingVoucher.status.in_(["staged", "pending_approval", "approved"]))
    elif status != "all":
        q = q.where(TallyStagingVoucher.status == status)

    if voucher_type:
        q = q.where(TallyStagingVoucher.voucher_type == voucher_type)

    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            q = q.where(TallyStagingVoucher.voucher_date >= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_from must be YYYY-MM-DD")

    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            q = q.where(TallyStagingVoucher.voucher_date <= dt)
        except ValueError:
            raise HTTPException(status_code=400, detail="date_to must be YYYY-MM-DD")

    vouchers = session.exec(
        q.order_by(TallyStagingVoucher.voucher_date.asc()).offset(skip).limit(limit)
    ).all()

    # Summary counts for UI badges
    counts = {}
    for s in ("staged", "pending_approval", "approved", "posting", "posted", "failed", "rejected"):
        counts[s] = session.exec(
            select(func.count(TallyStagingVoucher.id)).where(
                TallyStagingVoucher.company_id == current_user.company_id,
                TallyStagingVoucher.status == s,
            )
        ).one()

    # Amount summary for the review banner
    pending_amount = Decimal("0")
    for v in vouchers:
        try:
            pending_amount += Decimal(v.amount or "0")
        except InvalidOperation:
            pass

    return {
        "items": [_serialize_voucher(v) for v in vouchers],
        "total": len(vouchers),
        "pending_amount_inr": float(pending_amount),
        "status_counts": counts,
    }


@router.get("/staged/{staging_id}")
async def get_staged_voucher(
    staging_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Full detail for one staging voucher including raw Zoho Books payload."""
    v = _get_voucher(session, current_user.company_id, staging_id)
    result = _serialize_voucher(v, include_raw=True)

    # Attach related ActionLedger batch entry if any
    ledger = session.exec(
        select(ActionLedger).where(
            ActionLedger.company_id == current_user.company_id,
            ActionLedger.agent_name == "f3_books_sync",
            ActionLedger.entity_type == "company",
            ActionLedger.entity_id == current_user.company_id,
        ).order_by(ActionLedger.created_at.desc())
    ).first()
    result["batch_ledger"] = {
        "id": ledger.id,
        "status": ledger.status,
        "created_at": ledger.created_at,
        "rationale": ledger.rationale,
    } if ledger else None

    return result


# ---------------------------------------------------------------------------
# Approve / reject (single)
# ---------------------------------------------------------------------------

@router.post("/staged/{staging_id}/approve")
async def approve_voucher(
    staging_id: int,
    body: ApproveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Approve one staging voucher → queues push_voucher task to post to Tally."""
    v = _get_voucher(session, current_user.company_id, staging_id)

    if v.status not in ("staged", "pending_approval"):
        raise HTTPException(
            status_code=400,
            detail=f"Voucher is in status '{v.status}' — only staged/pending_approval can be approved.",
        )

    now = utc_now()
    v.status = "approved"
    v.approved_by_user_id = current_user.id
    v.approved_at = now
    v.rejection_reason = None
    v.updated_at = now
    session.add(v)
    session.flush()

    task_id = _queue_push_task(session, current_user.company_id, staging_id, current_user.id)
    session.commit()

    return {
        "staging_id": staging_id,
        "status": "approved",
        "push_task_id": task_id,
        "zoho_books_ref": v.zoho_books_ref,
        "voucher_type": v.voucher_type,
        "amount": v.amount,
        "message": "Voucher approved. Queued for Tally posting.",
    }


@router.post("/staged/{staging_id}/reject")
async def reject_voucher(
    staging_id: int,
    body: RejectRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Reject a staging voucher — it will not be posted to Tally.

    A reason is mandatory for the audit trail.
    """
    v = _get_voucher(session, current_user.company_id, staging_id)

    if v.status not in ("staged", "pending_approval"):
        raise HTTPException(
            status_code=400,
            detail=f"Voucher is in status '{v.status}' — only staged/pending_approval can be rejected.",
        )

    now = utc_now()
    v.status = "rejected"
    v.approved_by_user_id = current_user.id
    v.approved_at = now
    v.rejection_reason = body.reason
    v.updated_at = now
    session.add(v)
    session.commit()

    return {
        "staging_id": staging_id,
        "status": "rejected",
        "reason": body.reason,
        "zoho_books_ref": v.zoho_books_ref,
    }


# ---------------------------------------------------------------------------
# Bulk approve / reject
# ---------------------------------------------------------------------------

@router.post("/staged/bulk-approve")
async def bulk_approve_vouchers(
    body: BulkApproveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Batch-approve multiple staging vouchers in one click.

    This is the accountant's primary daily action:
      - Review the staged list
      - Select all (or filter by type/date)
      - Click Approve All

    Returns per-voucher outcome so the UI can highlight any that were skipped.
    """
    if not body.staging_ids:
        raise HTTPException(status_code=400, detail="staging_ids must not be empty")

    approved_ids: list[int] = []
    skipped_wrong_status: list[dict] = []
    task_ids: list[int] = []
    total_amount = Decimal("0")
    now = utc_now()

    for staging_id in body.staging_ids:
        try:
            v = _get_voucher(session, current_user.company_id, staging_id)
        except HTTPException:
            skipped_wrong_status.append({"id": staging_id, "reason": "not_found"})
            continue

        if v.status not in ("staged", "pending_approval"):
            skipped_wrong_status.append({"id": staging_id, "reason": v.status})
            continue

        v.status = "approved"
        v.approved_by_user_id = current_user.id
        v.approved_at = now
        v.rejection_reason = None
        v.updated_at = now
        session.add(v)
        session.flush()

        task_id = _queue_push_task(session, current_user.company_id, staging_id, current_user.id)
        approved_ids.append(staging_id)
        task_ids.append(task_id)

        try:
            total_amount += Decimal(v.amount or "0")
        except InvalidOperation:
            pass

    session.commit()

    return {
        "approved_count": len(approved_ids),
        "approved_staging_ids": approved_ids,
        "push_task_ids": task_ids,
        "total_amount_inr": float(total_amount),
        "skipped_count": len(skipped_wrong_status),
        "skipped": skipped_wrong_status,
        "message": (
            f"Approved {len(approved_ids)} voucher(s) totalling ₹{total_amount:,.2f}. "
            f"Queued for Tally posting."
        ),
    }


@router.post("/staged/bulk-reject")
async def bulk_reject_vouchers(
    body: BulkRejectRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Batch-reject multiple staging vouchers (e.g. wrong date range pulled)."""
    if not body.staging_ids:
        raise HTTPException(status_code=400, detail="staging_ids must not be empty")

    rejected_ids: list[int] = []
    skipped: list[dict] = []
    now = utc_now()

    for staging_id in body.staging_ids:
        try:
            v = _get_voucher(session, current_user.company_id, staging_id)
        except HTTPException:
            skipped.append({"id": staging_id, "reason": "not_found"})
            continue

        if v.status not in ("staged", "pending_approval"):
            skipped.append({"id": staging_id, "reason": v.status})
            continue

        v.status = "rejected"
        v.approved_by_user_id = current_user.id
        v.approved_at = now
        v.rejection_reason = body.reason
        v.updated_at = now
        session.add(v)
        rejected_ids.append(staging_id)

    session.commit()

    return {
        "rejected_count": len(rejected_ids),
        "rejected_staging_ids": rejected_ids,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "reason": body.reason,
    }


# ---------------------------------------------------------------------------
# Trigger actions
# ---------------------------------------------------------------------------

@router.post("/sync")
async def trigger_sync(
    body: SyncRequest = SyncRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Trigger a Zoho Books pull immediately.

    Normally runs on a daily schedule. Use this after:
    - Adding a new Zoho Books transaction manually
    - Changing the OAuth scope and reconnecting
    - Debugging a missed sync window
    """
    input_json: dict = {"action": "daily_sync"}
    if body.voucher_types:
        input_json["voucher_types"] = body.voucher_types

    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="daily_books_sync",
        assigned_agent="f3_books_sync",
        input_json=input_json,
        priority=4,
        actor_user_id=current_user.id,
    )
    session.commit()

    return {
        "task_id": task.id,
        "status": task.status,
        "voucher_types": body.voucher_types or "all",
        "message": "Zoho Books sync queued. Staged vouchers will appear in /books-sync/staged within seconds.",
    }


@router.post("/reconcile")
async def trigger_reconcile(
    body: ReconcileRequest = ReconcileRequest(),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Run a Zoho Books vs Tally reconciliation immediately."""
    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="books_tally_reconcile",
        assigned_agent="f3_books_sync",
        input_json={"action": "reconcile", "days": body.days},
        priority=3,
        actor_user_id=current_user.id,
    )
    session.commit()

    return {
        "task_id": task.id,
        "days": body.days,
        "message": f"Reconciliation queued for last {body.days} days. Results in /books-sync/kpis when complete.",
    }


@router.post("/retry")
async def trigger_retry(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Queue retry tasks for all failed vouchers under the retry cap (max 3)."""
    # Count eligible failed vouchers before queuing
    failed_count = session.exec(
        select(func.count(TallyStagingVoucher.id)).where(
            TallyStagingVoucher.company_id == current_user.company_id,
            TallyStagingVoucher.status == "failed",
            TallyStagingVoucher.retry_count < 3,
        )
    ).one()

    if not failed_count:
        return {
            "task_id": None,
            "failed_count": 0,
            "message": "No retryable failed vouchers found (all either resolved or hit max retries).",
        }

    task = create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type="retry_failed_tally_vouchers",
        assigned_agent="f3_books_sync",
        input_json={"action": "retry_failed"},
        priority=3,
        actor_user_id=current_user.id,
    )
    session.commit()

    return {
        "task_id": task.id,
        "failed_count": failed_count,
        "message": f"Retry queued for {failed_count} failed voucher(s).",
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

@router.get("/history")
async def get_history(
    days: int = Query(default=30, ge=1, le=365),
    status: Optional[str] = Query(default=None, description="posted | failed | rejected | skipped"),
    voucher_type: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Audit history of posted, failed, and rejected vouchers."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    q = select(TallyStagingVoucher).where(
        TallyStagingVoucher.company_id == current_user.company_id,
        TallyStagingVoucher.created_at >= cutoff,
    )

    if status:
        q = q.where(TallyStagingVoucher.status == status)
    else:
        q = q.where(TallyStagingVoucher.status.in_(["posted", "failed", "rejected", "skipped"]))

    if voucher_type:
        q = q.where(TallyStagingVoucher.voucher_type == voucher_type)

    vouchers = session.exec(
        q.order_by(TallyStagingVoucher.voucher_date.desc()).offset(skip).limit(limit)
    ).all()

    return {
        "items": [_serialize_voucher(v) for v in vouchers],
        "total": len(vouchers),
        "days": days,
    }


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

@router.get("/kpis")
async def get_kpis(
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Finance controller dashboard — Tally sync health at a glance.

    Shows drift, throughput, backlog, and last reconcile result.
    """
    company_id = current_user.company_id
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # --- KPI events ---
    kpi_rows = session.exec(
        select(AgentKpiEvent).where(
            AgentKpiEvent.company_id == company_id,
            AgentKpiEvent.agent_name == "f3_books_sync",
            AgentKpiEvent.created_at >= cutoff,
        )
    ).all()

    def _latest(metric: str) -> Optional[str]:
        rows = [r for r in kpi_rows if r.metric_name == metric]
        return rows[-1].metric_value if rows else None

    def _sum_metric(metric: str) -> float:
        return sum(float(r.metric_value or 0) for r in kpi_rows if r.metric_name == metric)

    drift_inr = _latest("tally_sync_drift_inr")
    drift_pct = _latest("tally_sync_drift_pct")
    watermark_ts = _latest("zoho_books_sync_watermark")
    last_sync_at: Optional[datetime] = None
    if watermark_ts:
        try:
            last_sync_at = datetime.fromtimestamp(float(watermark_ts), tz=timezone.utc)
        except (ValueError, OSError):
            pass

    staged_total = _sum_metric("staged_vouchers_count")
    posted_total = _sum_metric("tally_posted_count")
    failed_total = _sum_metric("tally_push_failed")

    # --- Live voucher counts ---
    status_counts: dict[str, int] = {}
    for s in ("staged", "pending_approval", "approved", "posting", "posted", "failed", "rejected"):
        status_counts[s] = session.exec(
            select(func.count(TallyStagingVoucher.id)).where(
                TallyStagingVoucher.company_id == company_id,
                TallyStagingVoucher.status == s,
            )
        ).one()

    # Amount posted in period
    posted_vouchers = session.exec(
        select(TallyStagingVoucher).where(
            TallyStagingVoucher.company_id == company_id,
            TallyStagingVoucher.status == "posted",
            TallyStagingVoucher.posted_at >= cutoff,
        )
    ).all()
    posted_amount = Decimal("0")
    for v in posted_vouchers:
        try:
            posted_amount += Decimal(v.amount or "0")
        except InvalidOperation:
            pass

    # Posting success rate
    total_attempts = int(posted_total) + int(failed_total)
    success_rate_pct = round(
        (int(posted_total) / total_attempts * 100) if total_attempts else 0.0, 1
    )

    # Failed vouchers requiring attention (hit max retries)
    exhausted_count = session.exec(
        select(func.count(TallyStagingVoucher.id)).where(
            TallyStagingVoucher.company_id == company_id,
            TallyStagingVoucher.status == "failed",
            TallyStagingVoucher.retry_count >= 3,
        )
    ).one()

    return {
        "period_days": days,
        "last_sync_at": last_sync_at,
        # Reconciliation
        "drift_inr": float(drift_inr) if drift_inr else None,
        "drift_pct": float(drift_pct) if drift_pct else None,
        "drift_alert": (float(drift_inr) > 5000) if drift_inr else False,
        # Throughput
        "staged_count": int(staged_total),
        "posted_count": int(posted_total),
        "failed_count": int(failed_total),
        "posted_amount_inr": float(posted_amount),
        "success_rate_pct": success_rate_pct,
        # Current backlog
        "pending_review_count": status_counts["staged"] + status_counts["pending_approval"],
        "approved_queued_count": status_counts["approved"] + status_counts["posting"],
        "failed_retryable_count": status_counts["failed"] - exhausted_count,
        "failed_exhausted_count": exhausted_count,
        "status_counts": status_counts,
    }

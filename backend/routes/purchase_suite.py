"""
Purchase Suite approval console — P1 Indent / P2 PO / P3 GRN.

Prefix: /crm/purchase

Endpoints
---------
GET  /purchase/indents                         — pending indent queue + status counts
GET  /purchase/indents/{id}                    — indent detail + lines
POST /purchase/indents/{id}/approve            — approve indent → queue p2_po:generate_po
POST /purchase/indents/{id}/reject             — reject indent with reason
POST /purchase/indents/bulk-approve            — batch approve A2 indents
POST /purchase/indents/scan                    — trigger p1_indent:daily_scan
GET  /purchase/orders                          — PO list by status
GET  /purchase/orders/{id}                     — PO detail + lines + GRNs
POST /purchase/orders/{id}/acknowledge         — mark PO acknowledged by Samsung
POST /purchase/orders/flag-overdue             — trigger p2_po:flag_overdue
POST /purchase/orders/generate                 — trigger p2_po:generate_po for an indent
GET  /purchase/grns                            — GRN list
GET  /purchase/grns/{id}                       — GRN detail + lines
POST /purchase/grns/{id}/resolve               — mark discrepancy resolved (approve ledger)
POST /purchase/grns/receive                    — trigger p3_grn:receive_goods
GET  /purchase/kpis                            — purchase KPIs (no hardcoded targets)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, col, select

from database import get_session
from models.models import (
    ActionLedger,
    AgentTask,
    GoodsReceiptNote,
    GRNLine,
    PurchaseIndent,
    PurchaseIndentLine,
    PurchaseOrder,
    PurchaseOrderLine,
    AgentKpiEvent,
)
from services.action_ledger import approve_action, reject_action

router = APIRouter(prefix="/purchase", tags=["purchase-suite"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ApproveBody(BaseModel):
    approved_by_user_id: int
    notes: Optional[str] = None


class RejectBody(BaseModel):
    rejected_by_user_id: int
    reason: str


class BulkApproveBody(BaseModel):
    ledger_ids: list[int]
    approved_by_user_id: int


class AcknowledgeBody(BaseModel):
    acknowledged_by_user_id: Optional[int] = None
    samsung_acknowledgement_ref: Optional[str] = None


class ResolveDiscrepancyBody(BaseModel):
    resolved_by_user_id: int
    resolution_notes: str


class ReceiveGoodsBody(BaseModel):
    po_id: int
    company_id: Optional[int] = None
    received_by_user_id: Optional[int] = None
    vehicle_number: Optional[str] = None
    delivery_challan_number: Optional[str] = None
    lines: list[dict]


# ---------------------------------------------------------------------------
# P1 Indent endpoints
# ---------------------------------------------------------------------------

@router.get("/indents")
async def list_indents(
    status: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(PurchaseIndent)
    if company_id:
        stmt = stmt.where(PurchaseIndent.company_id == company_id)
    if status:
        stmt = stmt.where(PurchaseIndent.status == status)
    else:
        stmt = stmt.where(PurchaseIndent.status.in_(["proposed", "approved"]))
    stmt = stmt.order_by(col(PurchaseIndent.created_at).desc()).offset(offset).limit(limit)
    indents = session.exec(stmt).all()

    counts: dict[str, int] = {}
    for row in session.exec(select(PurchaseIndent)):
        counts[row.status] = counts.get(row.status, 0) + 1

    return {
        "indents": [
            {
                "id": ind.id,
                "indent_number": ind.indent_number,
                "company_id": ind.company_id,
                "status": ind.status,
                "total_value_inr": str(ind.total_value_inr),
                "autonomy_level": ind.autonomy_level,
                "action_ledger_id": ind.action_ledger_id,
                "created_at": ind.created_at.isoformat(),
            }
            for ind in indents
        ],
        "status_counts": counts,
        "total": len(indents),
    }


@router.get("/indents/{indent_id}")
async def get_indent(indent_id: int, session: Session = Depends(get_session)):
    indent = session.get(PurchaseIndent, indent_id)
    if not indent:
        raise HTTPException(404, f"Indent {indent_id} not found")
    lines = session.exec(
        select(PurchaseIndentLine).where(PurchaseIndentLine.indent_id == indent_id)
    ).all()
    ledger = session.get(ActionLedger, indent.action_ledger_id) if indent.action_ledger_id else None
    return {
        "indent": indent.model_dump(),
        "lines": [l.model_dump() for l in lines],
        "ledger": ledger.model_dump() if ledger else None,
    }


@router.post("/indents/{indent_id}/approve")
async def approve_indent(
    indent_id: int,
    body: ApproveBody,
    session: Session = Depends(get_session),
):
    indent = session.get(PurchaseIndent, indent_id)
    if not indent:
        raise HTTPException(404, f"Indent {indent_id} not found")
    if indent.status != "proposed":
        raise HTTPException(400, f"Indent is {indent.status!r} — not approvable")

    indent.status = "approved"
    indent.approved_by_user_id = body.approved_by_user_id
    indent.approved_at = _utc_now()
    indent.updated_at = _utc_now()
    if body.notes:
        indent.notes = body.notes
    session.add(indent)

    if indent.action_ledger_id:
        await approve_action(
            session=session,
            ledger_id=indent.action_ledger_id,
            approved_by_user_id=body.approved_by_user_id,
        )

    # Queue p2_po:generate_po
    task = AgentTask(
        company_id=indent.company_id,
        agent_name="p2_po",
        task_type="generate_po",
        input_json={"action": "generate_po", "indent_id": indent_id},
        status="pending",
    )
    session.add(task)
    session.commit()

    return {
        "approved": True,
        "indent_id": indent_id,
        "task_id": task.id,
    }


@router.post("/indents/{indent_id}/reject")
async def reject_indent(
    indent_id: int,
    body: RejectBody,
    session: Session = Depends(get_session),
):
    indent = session.get(PurchaseIndent, indent_id)
    if not indent:
        raise HTTPException(404, f"Indent {indent_id} not found")
    if indent.status not in ("proposed", "draft"):
        raise HTTPException(400, f"Cannot reject indent in status {indent.status!r}")

    indent.status = "cancelled"
    indent.notes = body.reason
    indent.updated_at = _utc_now()
    session.add(indent)

    if indent.action_ledger_id:
        await reject_action(
            session=session,
            ledger_id=indent.action_ledger_id,
            rejection_note=body.reason,
            rejected_by_user_id=body.rejected_by_user_id,
        )

    session.commit()
    return {"rejected": True, "indent_id": indent_id}


@router.post("/indents/bulk-approve")
async def bulk_approve_indents(
    body: BulkApproveBody,
    session: Session = Depends(get_session),
):
    results: list[dict] = []
    for ledger_id in body.ledger_ids:
        ledger = session.get(ActionLedger, ledger_id)
        if not ledger or ledger.autonomy_level == "A1":
            results.append({"ledger_id": ledger_id, "skipped": True, "reason": "A1 or not found"})
            continue

        indent = session.exec(
            select(PurchaseIndent).where(PurchaseIndent.action_ledger_id == ledger_id)
        ).first()
        if not indent or indent.status != "proposed":
            results.append({"ledger_id": ledger_id, "skipped": True, "reason": "not in proposed state"})
            continue

        indent.status = "approved"
        indent.approved_by_user_id = body.approved_by_user_id
        indent.approved_at = _utc_now()
        indent.updated_at = _utc_now()
        session.add(indent)

        await approve_action(
            session=session,
            ledger_id=ledger_id,
            approved_by_user_id=body.approved_by_user_id,
        )

        task = AgentTask(
            company_id=indent.company_id,
            agent_name="p2_po",
            task_type="generate_po",
            input_json={"action": "generate_po", "indent_id": indent.id},
            status="pending",
        )
        session.add(task)
        session.flush()
        results.append({"ledger_id": ledger_id, "approved": True, "indent_id": indent.id, "task_id": task.id})

    session.commit()
    approved = sum(1 for r in results if r.get("approved"))
    return {"approved_count": approved, "results": results}


@router.post("/indents/scan")
async def trigger_indent_scan(
    company_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    task = AgentTask(
        company_id=company_id or 0,
        agent_name="p1_indent",
        task_type="daily_scan",
        input_json={"action": "daily_scan", "company_id": company_id},
        status="pending",
    )
    session.add(task)
    session.commit()
    return {"queued": True, "task_id": task.id}


# ---------------------------------------------------------------------------
# P2 PO endpoints
# ---------------------------------------------------------------------------

@router.get("/orders")
async def list_orders(
    status: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(PurchaseOrder)
    if company_id:
        stmt = stmt.where(PurchaseOrder.company_id == company_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    stmt = stmt.order_by(col(PurchaseOrder.created_at).desc()).offset(offset).limit(limit)
    orders = session.exec(stmt).all()

    counts: dict[str, int] = {}
    for row in session.exec(select(PurchaseOrder)):
        counts[row.status] = counts.get(row.status, 0) + 1

    return {
        "orders": [
            {
                "id": po.id,
                "po_number": po.po_number,
                "company_id": po.company_id,
                "indent_id": po.indent_id,
                "status": po.status,
                "total_value_inr": str(po.total_value_inr),
                "expected_delivery_date": po.expected_delivery_date.isoformat() if po.expected_delivery_date else None,
                "sent_at": po.sent_at.isoformat() if po.sent_at else None,
                "zoho_po_id": po.zoho_po_id,
                "created_at": po.created_at.isoformat(),
            }
            for po in orders
        ],
        "status_counts": counts,
    }


@router.get("/orders/{po_id}")
async def get_order(po_id: int, session: Session = Depends(get_session)):
    po = session.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, f"PO {po_id} not found")
    lines = session.exec(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
    ).all()
    grns = session.exec(
        select(GoodsReceiptNote).where(GoodsReceiptNote.po_id == po_id)
    ).all()
    return {
        "order": po.model_dump(),
        "lines": [l.model_dump() for l in lines],
        "grns": [
            {"id": g.id, "grn_number": g.grn_number, "status": g.status, "has_discrepancy": g.has_discrepancy}
            for g in grns
        ],
    }


@router.post("/orders/{po_id}/acknowledge")
async def acknowledge_order(
    po_id: int,
    body: AcknowledgeBody,
    session: Session = Depends(get_session),
):
    po = session.get(PurchaseOrder, po_id)
    if not po:
        raise HTTPException(404, f"PO {po_id} not found")
    if po.status not in ("sent", "draft"):
        raise HTTPException(400, f"PO is {po.status!r} — cannot acknowledge")

    po.status = "acknowledged"
    po.acknowledged_at = _utc_now()
    po.updated_at = _utc_now()
    if body.samsung_acknowledgement_ref:
        po.notes = f"Samsung ref: {body.samsung_acknowledgement_ref}"
    session.add(po)
    session.commit()
    return {"acknowledged": True, "po_id": po_id}


@router.post("/orders/flag-overdue")
async def trigger_flag_overdue(
    company_id: Optional[int] = None,
    session: Session = Depends(get_session),
):
    task = AgentTask(
        company_id=company_id or 0,
        agent_name="p2_po",
        task_type="flag_overdue",
        input_json={"action": "flag_overdue", "company_id": company_id},
        status="pending",
    )
    session.add(task)
    session.commit()
    return {"queued": True, "task_id": task.id}


@router.post("/orders/generate")
async def trigger_generate_po(
    indent_id: int,
    session: Session = Depends(get_session),
):
    indent = session.get(PurchaseIndent, indent_id)
    if not indent:
        raise HTTPException(404, f"Indent {indent_id} not found")
    task = AgentTask(
        company_id=indent.company_id,
        agent_name="p2_po",
        task_type="generate_po",
        input_json={"action": "generate_po", "indent_id": indent_id},
        status="pending",
    )
    session.add(task)
    session.commit()
    return {"queued": True, "task_id": task.id}


# ---------------------------------------------------------------------------
# P3 GRN endpoints
# ---------------------------------------------------------------------------

@router.get("/grns")
async def list_grns(
    status: Optional[str] = Query(None),
    company_id: Optional[int] = Query(None),
    has_discrepancy: Optional[bool] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    stmt = select(GoodsReceiptNote)
    if company_id:
        stmt = stmt.where(GoodsReceiptNote.company_id == company_id)
    if status:
        stmt = stmt.where(GoodsReceiptNote.status == status)
    if has_discrepancy is not None:
        stmt = stmt.where(GoodsReceiptNote.has_discrepancy == has_discrepancy)
    stmt = stmt.order_by(col(GoodsReceiptNote.received_at).desc()).offset(offset).limit(limit)
    grns = session.exec(stmt).all()

    counts: dict[str, int] = {}
    for row in session.exec(select(GoodsReceiptNote)):
        counts[row.status] = counts.get(row.status, 0) + 1

    return {
        "grns": [
            {
                "id": g.id,
                "grn_number": g.grn_number,
                "company_id": g.company_id,
                "po_id": g.po_id,
                "status": g.status,
                "has_discrepancy": g.has_discrepancy,
                "discrepancy_notes": g.discrepancy_notes,
                "received_at": g.received_at.isoformat(),
            }
            for g in grns
        ],
        "status_counts": counts,
    }


@router.get("/grns/{grn_id}")
async def get_grn(grn_id: int, session: Session = Depends(get_session)):
    grn = session.get(GoodsReceiptNote, grn_id)
    if not grn:
        raise HTTPException(404, f"GRN {grn_id} not found")
    lines = session.exec(
        select(GRNLine).where(GRNLine.grn_id == grn_id)
    ).all()
    ledger = session.get(ActionLedger, grn.action_ledger_id) if grn.action_ledger_id else None
    return {
        "grn": grn.model_dump(),
        "lines": [l.model_dump() for l in lines],
        "ledger": ledger.model_dump() if ledger else None,
    }


@router.post("/grns/{grn_id}/resolve")
async def resolve_discrepancy(
    grn_id: int,
    body: ResolveDiscrepancyBody,
    session: Session = Depends(get_session),
):
    grn = session.get(GoodsReceiptNote, grn_id)
    if not grn:
        raise HTTPException(404, f"GRN {grn_id} not found")
    if not grn.has_discrepancy:
        raise HTTPException(400, "GRN has no discrepancy to resolve")

    grn.status = "verified"
    grn.discrepancy_notes = (grn.discrepancy_notes or "") + f" | RESOLVED: {body.resolution_notes}"
    grn.updated_at = _utc_now()
    session.add(grn)

    if grn.action_ledger_id:
        await approve_action(
            session=session,
            ledger_id=grn.action_ledger_id,
            approved_by_user_id=body.resolved_by_user_id,
        )

    session.commit()
    return {"resolved": True, "grn_id": grn_id}


@router.post("/grns/receive")
async def trigger_receive_goods(
    body: ReceiveGoodsBody,
    session: Session = Depends(get_session),
):
    po = session.get(PurchaseOrder, body.po_id)
    if not po:
        raise HTTPException(404, f"PO {body.po_id} not found")

    task = AgentTask(
        company_id=body.company_id or po.company_id,
        agent_name="p3_grn",
        task_type="receive_goods",
        input_json={
            "action": "receive_goods",
            "po_id": body.po_id,
            "company_id": body.company_id or po.company_id,
            "received_by_user_id": body.received_by_user_id,
            "vehicle_number": body.vehicle_number,
            "delivery_challan_number": body.delivery_challan_number,
            "lines": body.lines,
        },
        status="pending",
    )
    session.add(task)
    session.commit()
    return {"queued": True, "task_id": task.id}


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

@router.get("/kpis")
async def purchase_kpis(
    company_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
):
    # Indent KPIs
    indent_stmt = select(PurchaseIndent)
    if company_id:
        indent_stmt = indent_stmt.where(PurchaseIndent.company_id == company_id)
    indents = session.exec(indent_stmt).all()

    total_indents = len(indents)
    pending_indents = sum(1 for i in indents if i.status == "proposed")
    approved_indents = sum(1 for i in indents if i.status == "approved")

    # PO KPIs
    po_stmt = select(PurchaseOrder)
    if company_id:
        po_stmt = po_stmt.where(PurchaseOrder.company_id == company_id)
    orders = session.exec(po_stmt).all()

    overdue_orders = sum(
        1 for po in orders
        if po.expected_delivery_date
        and po.expected_delivery_date < _utc_now()
        and po.status not in ("delivered", "cancelled")
    )

    # GRN KPIs
    grn_stmt = select(GoodsReceiptNote)
    if company_id:
        grn_stmt = grn_stmt.where(GoodsReceiptNote.company_id == company_id)
    grns = session.exec(grn_stmt).all()

    total_grns = len(grns)
    discrepancy_grns = sum(1 for g in grns if g.has_discrepancy)
    discrepancy_rate_pct = (
        round(discrepancy_grns / total_grns * 100, 2) if total_grns else None
    )

    # KPI events
    kpi_stmt = select(AgentKpiEvent).where(
        AgentKpiEvent.agent_name.in_(["p1_indent", "p2_po", "p3_grn"])
    )
    if company_id:
        kpi_stmt = kpi_stmt.where(AgentKpiEvent.company_id == company_id)
    kpi_events = session.exec(kpi_stmt).all()

    total_value_proposed = sum(
        float(e.metric_value) for e in kpi_events if e.metric_name == "indent_value_proposed_inr"
    )
    total_value_ordered = sum(
        float(e.metric_value) for e in kpi_events if e.metric_name == "po_value_inr"
    )
    total_units_received = sum(
        float(e.metric_value) for e in kpi_events if e.metric_name == "units_received"
    )

    return {
        "indents": {
            "total": total_indents,
            "pending_approval": pending_indents,
            "approved": approved_indents,
            "total_value_proposed_inr": round(total_value_proposed, 2),
        },
        "purchase_orders": {
            "total": len(orders),
            "overdue": overdue_orders,
            "total_value_ordered_inr": round(total_value_ordered, 2),
            "status_counts": {
                s: sum(1 for po in orders if po.status == s)
                for s in {po.status for po in orders}
            },
        },
        "grns": {
            "total": total_grns,
            "discrepancy_count": discrepancy_grns,
            "discrepancy_rate_pct": discrepancy_rate_pct,
            "total_units_received": total_units_received,
        },
    }

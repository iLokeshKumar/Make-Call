"""
P3 GRN Agent — Goods Receipt Note processing.

Actions
-------
receive_goods : Input GRN lines against a PO → post stock updates + serial capture.
                A3 for clean receipts (qty matches, no damage, all serials valid).
                A1 for any discrepancy (short delivery, model mismatch, damage, excess).
retry_pending : Retry GRNs stuck in draft (stock update failed earlier).
reconcile_po  : Compare all GRN receipts vs PO ordered quantities.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, col

from database import engine
from models.models import (
    AgentTask,
    Company,
    Product,
    PurchaseOrder,
    PurchaseOrderLine,
    GoodsReceiptNote,
    GRNLine,
    SerialRegistry,
)
from services.action_ledger import log_action, record_kpi

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _next_grn_number(session: Session, company_id: int) -> str:
    from sqlmodel import func
    count = session.exec(
        select(func.count(GoodsReceiptNote.id)).where(
            GoodsReceiptNote.company_id == company_id
        )
    ).one()
    return f"GRN-{company_id:04d}-{count + 1:06d}"


def _detect_discrepancy(line: GRNLine) -> str | None:
    """Return discrepancy_type string or None if clean."""
    if line.quantity_rejected > 0:
        return "damage"
    if line.quantity_received > line.quantity_ordered:
        return "excess_delivery"
    if line.quantity_received < line.quantity_ordered:
        return "short_delivery"
    if line.quantity_accepted != line.quantity_received:
        return "serial_mismatch"
    return None


async def run(session_ext: Session | None = None, task: AgentTask | None = None) -> dict:
    action = (task.input_json or {}).get("action", "receive_goods") if task else "receive_goods"

    with Session(engine) as session:
        if action == "receive_goods":
            return await _receive_goods(session, task)
        if action == "retry_pending":
            company_id = (task.input_json or {}).get("company_id")
            return await _retry_pending(session, task, company_id)
        if action == "reconcile_po":
            po_id = (task.input_json or {}).get("po_id")
            return await _reconcile_po(session, po_id)
        return {"error": f"Unknown action: {action}"}


async def _receive_goods(session: Session, task: AgentTask | None) -> dict:
    """
    Input format (task.input_json):
    {
        "action": "receive_goods",
        "po_id": 42,
        "company_id": 1,
        "received_by_user_id": 7,
        "vehicle_number": "TN-01-AB-1234",
        "delivery_challan_number": "DC/2026/00123",
        "lines": [
            {
                "po_line_id": 101,
                "product_id": 55,
                "sku_snapshot": "SM-S928B",
                "product_name_snapshot": "65-inch 4K LED Television",
                "quantity_ordered": 10,
                "quantity_received": 9,
                "quantity_accepted": 9,
                "quantity_rejected": 0,
                "serial_numbers": ["IMEI1", "IMEI2", ...],
                "unit_cost": "85000.00"
            }
        ]
    }
    """
    inp = task.input_json or {} if task else {}
    po_id = inp.get("po_id")
    company_id = inp.get("company_id")
    received_by = inp.get("received_by_user_id")
    vehicle_number = inp.get("vehicle_number")
    challan_number = inp.get("delivery_challan_number")
    raw_lines: list[dict] = inp.get("lines", [])

    if not po_id:
        return {"error": "po_id required"}
    if not raw_lines:
        return {"error": "lines required"}

    po = session.get(PurchaseOrder, po_id)
    if not po:
        return {"error": f"PO {po_id} not found"}
    if po.status in ("cancelled", "delivered"):
        return {"error": f"PO {po_id} is {po.status!r} — cannot receive goods"}
    if not company_id:
        company_id = po.company_id

    grn_number = _next_grn_number(session, company_id)
    grn = GoodsReceiptNote(
        company_id=company_id,
        grn_number=grn_number,
        po_id=po_id,
        received_by_user_id=received_by,
        status="draft",
        has_discrepancy=False,
        vehicle_number=vehicle_number,
        delivery_challan_number=challan_number,
    )
    session.add(grn)
    session.flush()

    grn_lines: list[GRNLine] = []
    has_discrepancy = False
    discrepancy_notes: list[str] = []
    total_accepted = 0

    for raw in raw_lines:
        qty_ordered = int(raw.get("quantity_ordered", 0))
        qty_received = int(raw.get("quantity_received", 0))
        qty_accepted = int(raw.get("quantity_accepted", qty_received))
        qty_rejected = int(raw.get("quantity_rejected", 0))
        serial_numbers: list[str] = raw.get("serial_numbers", [])

        # Serial count is ground truth when provided
        if serial_numbers and len(serial_numbers) != qty_accepted:
            qty_accepted = len(serial_numbers)

        unit_cost_str = raw.get("unit_cost", "0.00")
        unit_cost = Decimal(str(unit_cost_str))

        grn_line = GRNLine(
            company_id=company_id,
            grn_id=grn.id,
            po_line_id=raw.get("po_line_id"),
            product_id=raw.get("product_id"),
            sku_snapshot=raw.get("sku_snapshot"),
            product_name_snapshot=raw.get("product_name_snapshot", ""),
            quantity_ordered=qty_ordered,
            quantity_received=qty_received,
            quantity_accepted=qty_accepted,
            quantity_rejected=qty_rejected,
            serial_numbers=serial_numbers,
            unit_cost=unit_cost,
        )

        disc_type = _detect_discrepancy(grn_line)
        if disc_type:
            grn_line.discrepancy_type = disc_type
            has_discrepancy = True
            discrepancy_notes.append(
                f"{grn_line.product_name_snapshot}: {disc_type} "
                f"(ordered={qty_ordered}, received={qty_received}, accepted={qty_accepted})"
            )

        session.add(grn_line)
        grn_lines.append(grn_line)
        total_accepted += qty_accepted

    session.flush()

    # --- Update product stock and capture serials ---
    stock_update_errors: list[str] = []
    for grn_line in grn_lines:
        if grn_line.product_id and grn_line.quantity_accepted > 0:
            product = session.get(Product, grn_line.product_id)
            if product:
                product.stock = (product.stock or 0) + grn_line.quantity_accepted
                session.add(product)

        # SerialRegistry: one row per IMEI/serial
        for serial in grn_line.serial_numbers:
            reg = SerialRegistry(
                company_id=company_id,
                product_id=grn_line.product_id,
                serial_number=serial,
                status="in_stock",
                po_number=po.po_number,
                grn_date=_utc_now(),
                vendor_name=po.vendor_name,
            )
            try:
                session.add(reg)
                session.flush()
            except IntegrityError:
                session.rollback()
                stock_update_errors.append(f"Duplicate serial {serial!r} for product {grn_line.product_id}")
                logger.warning("[P3] Duplicate serial %r — flagging discrepancy", serial)
                grn_line.discrepancy_type = grn_line.discrepancy_type or "serial_mismatch"
                grn_line.discrepancy_notes = (grn_line.discrepancy_notes or "") + f" Duplicate: {serial}"
                has_discrepancy = True
                session.add(grn_line)
                session.flush()

    grn.has_discrepancy = has_discrepancy
    grn.discrepancy_notes = "; ".join(discrepancy_notes) if discrepancy_notes else None

    # Autonomy: A3 clean, A1 any discrepancy
    autonomy = "A1" if has_discrepancy else "A3"
    grn.status = "verified" if not has_discrepancy else "discrepancy_flagged"

    session.flush()

    ledger_id = await log_action(
        session=session,
        agent_name="p3_grn",
        action_type="grn_posted" if not has_discrepancy else "grn_discrepancy_flagged",
        entity_type="GoodsReceiptNote",
        entity_id=grn.id,
        company_id=company_id,
        payload={
            "grn_number": grn_number,
            "po_id": po_id,
            "po_number": po.po_number,
            "lines_count": len(grn_lines),
            "total_accepted": total_accepted,
            "has_discrepancy": has_discrepancy,
            "discrepancy_notes": discrepancy_notes,
            "serial_errors": stock_update_errors,
        },
        autonomy_level=autonomy,
        requires_approval=(autonomy == "A1"),
        agent_task_id=task.id if task else None,
    )
    grn.action_ledger_id = ledger_id

    # Update PO status
    all_grn_lines = session.exec(
        select(GRNLine).where(GRNLine.grn_id == grn.id)
    ).all()
    po_lines = session.exec(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
    ).all()
    for pol in po_lines:
        received_for_pol = sum(
            gl.quantity_accepted
            for gl in all_grn_lines
            if gl.po_line_id == pol.id
        )
        pol.quantity_received = (pol.quantity_received or 0) + received_for_pol
        session.add(pol)

    total_ordered = sum(pol.quantity_ordered for pol in po_lines)
    total_received = sum(pol.quantity_received for pol in po_lines)
    if total_received >= total_ordered:
        po.status = "delivered"
    elif total_received > 0:
        po.status = "partial_delivery"
    po.updated_at = _utc_now()
    session.add(po)

    session.commit()

    record_kpi(
        session=session,
        company_id=company_id,
        agent_name="p3_grn",
        metric_name="units_received",
        metric_value=float(total_accepted),
        entity_type="GoodsReceiptNote",
        entity_id=grn.id,
    )
    if has_discrepancy:
        record_kpi(
            session=session,
            company_id=company_id,
            agent_name="p3_grn",
            metric_name="grn_discrepancy_count",
            metric_value=1.0,
            entity_type="GoodsReceiptNote",
            entity_id=grn.id,
        )

    logger.info(
        "[P3] GRN %s posted: %d lines, %d units accepted, discrepancy=%s, autonomy=%s",
        grn_number, len(grn_lines), total_accepted, has_discrepancy, autonomy,
    )

    return {
        "action": "receive_goods",
        "grn_id": grn.id,
        "grn_number": grn_number,
        "total_accepted": total_accepted,
        "has_discrepancy": has_discrepancy,
        "discrepancy_notes": discrepancy_notes,
        "autonomy_level": autonomy,
        "po_status": po.status,
        "errors": stock_update_errors,
    }


async def _retry_pending(session: Session, task: AgentTask | None, company_id: int | None) -> dict:
    stmt = select(GoodsReceiptNote).where(GoodsReceiptNote.status == "draft")
    if company_id:
        stmt = stmt.where(GoodsReceiptNote.company_id == company_id)
    pending = session.exec(stmt).all()

    retried = 0
    errors: list[str] = []
    for grn in pending:
        lines = session.exec(
            select(GRNLine).where(GRNLine.grn_id == grn.id)
        ).all()
        try:
            for line in lines:
                if line.product_id and line.quantity_accepted > 0:
                    product = session.get(Product, line.product_id)
                    if product:
                        product.stock = (product.stock or 0) + line.quantity_accepted
                        session.add(product)
            grn.status = "verified"
            session.add(grn)
            session.commit()
            retried += 1
        except Exception as exc:
            session.rollback()
            errors.append(f"GRN {grn.grn_number}: {exc}")

    return {"action": "retry_pending", "retried": retried, "errors": errors}


async def _reconcile_po(session: Session, po_id: int | None) -> dict:
    if not po_id:
        return {"error": "po_id required"}
    po = session.get(PurchaseOrder, po_id)
    if not po:
        return {"error": f"PO {po_id} not found"}

    po_lines = session.exec(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po_id)
    ).all()

    grns = session.exec(
        select(GoodsReceiptNote).where(GoodsReceiptNote.po_id == po_id)
    ).all()
    grn_ids = [g.id for g in grns]

    grn_line_map: dict[int, int] = {}  # po_line_id → total_accepted
    if grn_ids:
        all_grn_lines = session.exec(
            select(GRNLine).where(col(GRNLine.grn_id).in_(grn_ids))
        ).all()
        for gl in all_grn_lines:
            if gl.po_line_id:
                grn_line_map[gl.po_line_id] = grn_line_map.get(gl.po_line_id, 0) + gl.quantity_accepted

    summary = []
    for pol in po_lines:
        received = grn_line_map.get(pol.id, 0)
        summary.append({
            "po_line_id": pol.id,
            "product": pol.product_name_snapshot,
            "ordered": pol.quantity_ordered,
            "received": received,
            "outstanding": pol.quantity_ordered - received,
        })

    total_ordered = sum(p["ordered"] for p in summary)
    total_received = sum(p["received"] for p in summary)

    return {
        "action": "reconcile_po",
        "po_id": po_id,
        "po_number": po.po_number,
        "po_status": po.status,
        "total_ordered": total_ordered,
        "total_received": total_received,
        "outstanding": total_ordered - total_received,
        "lines": summary,
    }

"""
P1 Indent Agent — Demand scanning and purchase indent proposals.

Actions
-------
daily_scan   : Scan all products below reorder level → PurchaseIndent proposals.
               A2 for routine (<= ₹5L), A1 for high-value (> ₹5L).
refresh_indent: Re-compute a single existing draft/proposed indent.
cancel_indent : Cancel a proposed indent (before PO raised).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlmodel import Session, select, col

from database import engine
from models.models import (
    AgentTask,
    ActionLedger,
    AgentKpiEvent,
    Company,
    Product,
    PurchaseIndent,
    PurchaseIndentLine,
)
from services.action_ledger import (
    log_action,
    approve_action,
    reject_action,
    record_kpi,
)

logger = logging.getLogger(__name__)

# Indents above this threshold require A1 human approval; below → A2 batch review
HIGH_VALUE_THRESHOLD_INR = Decimal("500000.00")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _next_indent_number(session: Session, company_id: int) -> str:
    from sqlmodel import func
    count = session.exec(
        select(func.count(PurchaseIndent.id)).where(
            PurchaseIndent.company_id == company_id
        )
    ).one()
    return f"IND-{company_id:04d}-{count + 1:06d}"


async def run(session_ext: Session | None = None, task: AgentTask | None = None) -> dict:
    action = (task.input_json or {}).get("action", "daily_scan") if task else "daily_scan"
    company_id = (task.input_json or {}).get("company_id") if task else None

    with Session(engine) as session:
        if action == "daily_scan":
            return await _daily_scan(session, task, company_id)
        if action == "refresh_indent":
            indent_id = (task.input_json or {}).get("indent_id")
            return await _refresh_indent(session, task, indent_id)
        if action == "cancel_indent":
            indent_id = (task.input_json or {}).get("indent_id")
            reason = (task.input_json or {}).get("reason", "")
            return await _cancel_indent(session, task, indent_id, reason)
        return {"error": f"Unknown action: {action}"}


async def _daily_scan(session: Session, task: AgentTask | None, company_id: int | None) -> dict:
    """Scan all products below reorder_level; emit PurchaseIndent proposals."""
    company_ids = [company_id] if company_id else list(
        session.exec(select(Company.id).where(col(Company.id) > 0)).all()
    )

    total_indents = 0
    total_lines = 0
    errors: list[str] = []

    for cid in company_ids:
        try:
            created, lines = await _scan_company(session, task, cid)
            total_indents += created
            total_lines += lines
        except Exception as exc:
            logger.error("[P1] daily_scan error company %s: %s", cid, exc)
            errors.append(f"company {cid}: {exc}")

    return {
        "action": "daily_scan",
        "indents_created": total_indents,
        "lines_created": total_lines,
        "errors": errors,
    }


async def _scan_company(session: Session, task: AgentTask | None, company_id: int) -> tuple[int, int]:
    """Return (indent_count, line_count) created for this company."""
    products = session.exec(
        select(Product).where(
            Product.company_id == company_id,
            col(Product.stock) < col(Product.reorder_level),
        )
    ).all()

    if not products:
        return 0, 0

    # Group all under-stock products into one indent per company per day
    indent_number = _next_indent_number(session, company_id)
    indent = PurchaseIndent(
        company_id=company_id,
        indent_number=indent_number,
        status="draft",
        total_value_inr=Decimal("0.00"),
    )
    session.add(indent)
    session.flush()  # get indent.id

    total_value = Decimal("0.00")
    lines_created = 0

    for product in products:
        if product.reorder_level is None:
            continue
        qty_needed = product.reorder_level - product.stock
        if qty_needed <= 0:
            continue

        # Use last known unit cost from product; if zero, indent still raised with zero cost
        unit_cost = Decimal(str(product.price or "0.00"))
        line_total = unit_cost * qty_needed

        line = PurchaseIndentLine(
            company_id=company_id,
            indent_id=indent.id,
            product_id=product.id,
            sku_snapshot=getattr(product, "sku", None),
            product_name_snapshot=product.name,
            current_stock=product.stock,
            reorder_level=product.reorder_level,
            quantity_to_order=qty_needed,
            unit_cost=unit_cost,
            line_total=line_total,
        )
        session.add(line)
        total_value += line_total
        lines_created += 1

    indent.total_value_inr = total_value
    autonomy = "A1" if total_value > HIGH_VALUE_THRESHOLD_INR else "A2"
    indent.autonomy_level = autonomy
    indent.status = "proposed"

    session.flush()

    # Action Ledger entry
    ledger_id = await log_action(
        session=session,
        agent_name="p1_indent",
        action_type="purchase_indent_proposed",
        entity_type="PurchaseIndent",
        entity_id=indent.id,
        company_id=company_id,
        payload={
            "indent_number": indent_number,
            "product_count": lines_created,
            "total_value_inr": str(total_value),
            "autonomy_level": autonomy,
        },
        autonomy_level=autonomy,
        requires_approval=(autonomy == "A1"),
        agent_task_id=task.id if task else None,
    )
    indent.action_ledger_id = ledger_id

    session.commit()
    session.refresh(indent)

    record_kpi(
        session=session,
        company_id=company_id,
        agent_name="p1_indent",
        metric_name="indent_value_proposed_inr",
        metric_value=float(total_value),
        entity_type="PurchaseIndent",
        entity_id=indent.id,
    )

    logger.info(
        "[P1] company=%s indent=%s lines=%d value=%.2f autonomy=%s",
        company_id, indent_number, lines_created, total_value, autonomy,
    )
    return 1, lines_created


async def _refresh_indent(session: Session, task: AgentTask | None, indent_id: int | None) -> dict:
    if not indent_id:
        return {"error": "indent_id required"}
    indent = session.get(PurchaseIndent, indent_id)
    if not indent:
        return {"error": f"Indent {indent_id} not found"}
    if indent.status not in ("draft", "proposed"):
        return {"error": f"Cannot refresh indent in status {indent.status!r}"}

    lines = session.exec(
        select(PurchaseIndentLine).where(PurchaseIndentLine.indent_id == indent_id)
    ).all()

    total_value = Decimal("0.00")
    for line in lines:
        product = session.get(Product, line.product_id)
        if not product:
            continue
        line.current_stock = product.stock
        line.reorder_level = product.reorder_level
        qty_needed = max(product.reorder_level - product.stock, 0)
        line.quantity_to_order = qty_needed
        unit_cost = Decimal(str(product.price or "0.00"))
        line.unit_cost = unit_cost
        line.line_total = unit_cost * qty_needed
        total_value += line.line_total
        session.add(line)

    indent.total_value_inr = total_value
    indent.autonomy_level = "A1" if total_value > HIGH_VALUE_THRESHOLD_INR else "A2"
    indent.updated_at = _utc_now()
    session.add(indent)
    session.commit()

    return {"refreshed": True, "indent_id": indent_id, "total_value_inr": str(total_value)}


async def _cancel_indent(
    session: Session, task: AgentTask | None, indent_id: int | None, reason: str
) -> dict:
    if not indent_id:
        return {"error": "indent_id required"}
    indent = session.get(PurchaseIndent, indent_id)
    if not indent:
        return {"error": f"Indent {indent_id} not found"}
    if indent.status == "po_raised":
        return {"error": "Cannot cancel indent — PO already raised"}
    if indent.status == "cancelled":
        return {"error": "Already cancelled"}

    indent.status = "cancelled"
    indent.notes = reason or indent.notes
    indent.updated_at = _utc_now()
    session.add(indent)

    if indent.action_ledger_id:
        await reject_action(
            session=session,
            ledger_id=indent.action_ledger_id,
            rejection_note=reason or "Cancelled by agent",
            rejected_by_user_id=None,
        )

    session.commit()
    return {"cancelled": True, "indent_id": indent_id}

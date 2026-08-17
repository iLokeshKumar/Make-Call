"""
P2 PO Generator Agent — Converts approved indents into purchase orders.

Actions
-------
generate_po    : Approved indent → PurchaseOrder + PurchaseOrderLines → Zoho Books PO.
                 Emails the PO to the vendor contact. A2 autonomy (FM reviews Zoho sync).
flag_overdue   : Daily scan — POs past expected_delivery_date → flag + notify.
cancel_po      : Cancel a sent PO (before delivery).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import httpx
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
    PurchaseOrder,
    PurchaseOrderLine,
    OAuthToken,
)
from services.action_ledger import log_action, record_kpi
from services.email_service import send_email

logger = logging.getLogger(__name__)

ZOHO_BOOKS_API = "https://www.zohoapis.com/books/v3"
DEFAULT_DELIVERY_DAYS = 14  # override via env VENDOR_DELIVERY_DAYS


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _delivery_days() -> int:
    try:
        return int(os.getenv("VENDOR_DELIVERY_DAYS", str(DEFAULT_DELIVERY_DAYS)))
    except ValueError:
        return DEFAULT_DELIVERY_DAYS


def _next_po_number(session: Session, company_id: int) -> str:
    from sqlmodel import func
    count = session.exec(
        select(func.count(PurchaseOrder.id)).where(
            PurchaseOrder.company_id == company_id
        )
    ).one()
    return f"PO-{company_id:04d}-{count + 1:06d}"


async def _get_books_token(session: Session, company_id: int) -> str | None:
    for provider in ("zoho_books", "zoho"):
        token = session.exec(
            select(OAuthToken).where(
                OAuthToken.company_id == company_id,
                OAuthToken.provider == provider,
            )
        ).first()
        if token and token.access_token:
            return token.access_token
    return None


async def _get_books_org_id(session: Session, company_id: int) -> str | None:
    company = session.get(Company, company_id)
    if company:
        settings = getattr(company, "settings_json", None) or {}
        return settings.get("zoho_books_org_id")
    return None


async def _create_zoho_books_po(
    access_token: str,
    org_id: str,
    po: PurchaseOrder,
    lines: list[PurchaseOrderLine],
) -> str | None:
    """Push PO to Zoho Books; return zoho_po_id or None on failure."""
    line_items = []
    for line in lines:
        item: dict = {
            "name": line.product_name_snapshot,
            "quantity": line.quantity_ordered,
            "rate": float(line.unit_cost),
        }
        if line.sku_snapshot:
            item["sku"] = line.sku_snapshot
        line_items.append(item)

    payload = {
        "vendor_name": po.vendor_name,
        "purchaseorder_number": po.po_number,
        "date": po.created_at.strftime("%Y-%m-%d"),
        "line_items": line_items,
    }
    if po.expected_delivery_date:
        payload["delivery_date"] = po.expected_delivery_date.strftime("%Y-%m-%d")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{ZOHO_BOOKS_API}/purchaseorders",
                params={"organization_id": org_id},
                headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
                json=payload,
            )
        if resp.status_code == 201:
            return resp.json().get("purchaseorder", {}).get("purchaseorder_id")
        logger.warning("[P2] Zoho Books PO creation failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        logger.error("[P2] Zoho Books PO creation error: %s", exc)
    return None


async def run(session_ext: Session | None = None, task: AgentTask | None = None) -> dict:
    action = (task.input_json or {}).get("action", "generate_po") if task else "generate_po"

    with Session(engine) as session:
        if action == "generate_po":
            indent_id = (task.input_json or {}).get("indent_id")
            return await _generate_po(session, task, indent_id)
        if action == "flag_overdue":
            company_id = (task.input_json or {}).get("company_id")
            return await _flag_overdue(session, task, company_id)
        if action == "cancel_po":
            po_id = (task.input_json or {}).get("po_id")
            reason = (task.input_json or {}).get("reason", "")
            return await _cancel_po(session, task, po_id, reason)
        return {"error": f"Unknown action: {action}"}


async def _generate_po(session: Session, task: AgentTask | None, indent_id: int | None) -> dict:
    inp = task.input_json or {} if task else {}
    if not indent_id:
        return {"error": "indent_id required"}

    indent = session.get(PurchaseIndent, indent_id)
    if not indent:
        return {"error": f"Indent {indent_id} not found"}
    if indent.status != "approved":
        return {"error": f"Indent {indent_id} is not approved (status={indent.status!r})"}

    company_id = indent.company_id
    indent_lines = session.exec(
        select(PurchaseIndentLine).where(PurchaseIndentLine.indent_id == indent_id)
    ).all()
    if not indent_lines:
        return {"error": "Indent has no lines"}

    po_number = _next_po_number(session, company_id)
    delivery_date = _utc_now() + timedelta(days=_delivery_days())

    # Vendor name + contact from task input or env fallback
    vendor_name = (
        inp.get("vendor_name")
        or os.getenv(f"VENDOR_NAME_{company_id}")
        or os.getenv("VENDOR_NAME", "")
    )
    vendor_email = (
        inp.get("vendor_contact_email")
        or os.getenv(f"VENDOR_CONTACT_EMAIL_{company_id}")
        or os.getenv("VENDOR_CONTACT_EMAIL", "")
    )

    po = PurchaseOrder(
        company_id=company_id,
        po_number=po_number,
        indent_id=indent_id,
        vendor_name=vendor_name,
        vendor_contact_email=vendor_email or None,
        status="draft",
        total_value_inr=indent.total_value_inr,
        expected_delivery_date=delivery_date,
    )
    session.add(po)
    session.flush()

    po_lines: list[PurchaseOrderLine] = []
    for il in indent_lines:
        pol = PurchaseOrderLine(
            company_id=company_id,
            po_id=po.id,
            product_id=il.product_id,
            sku_snapshot=il.sku_snapshot,
            product_name_snapshot=il.product_name_snapshot,
            quantity_ordered=il.quantity_to_order,
            quantity_received=0,
            unit_cost=il.unit_cost,
            line_total=il.line_total,
        )
        session.add(pol)
        po_lines.append(pol)
    session.flush()

    # --- Zoho Books sync ---
    zoho_synced = False
    access_token = await _get_books_token(session, company_id)
    org_id = await _get_books_org_id(session, company_id)

    if access_token and org_id:
        zoho_po_id = await _create_zoho_books_po(access_token, org_id, po, po_lines)
        if zoho_po_id:
            po.zoho_po_id = zoho_po_id
            zoho_synced = True
    else:
        logger.warning("[P2] Zoho Books token/org not configured for company %s — skipping sync", company_id)

    # --- Email to DSE ---
    email_sent = False
    if vendor_email:
        try:
            lines_text = "\n".join(
                f"  {pol.product_name_snapshot}  qty={pol.quantity_ordered}  @₹{pol.unit_cost}"
                for pol in po_lines
            )
            body = (
                f"Dear {vendor_name or 'Vendor'},\n\n"
                f"Please find our Purchase Order {po_number} below.\n\n"
                f"{lines_text}\n\n"
                f"Total: ₹{indent.total_value_inr}\n"
                f"Expected delivery: {delivery_date.strftime('%d %b %Y')}\n\n"
                f"Regards,\nYexis Electronics"
            )
            await send_email(
                to=vendor_email,
                subject=f"Purchase Order {po_number} — Yexis Electronics",
                body=body,
            )
            email_sent = True
            po.status = "sent"
            po.sent_at = _utc_now()
        except Exception as exc:
            logger.warning("[P2] Vendor email failed: %s", exc)
            po.status = "draft"
    else:
        po.status = "sent"
        po.sent_at = _utc_now()
        logger.info("[P2] VENDOR_CONTACT_EMAIL not set — PO %s marked sent without email", po_number)

    # Ledger entry (A2 — FM reviews Zoho sync; no individual approval gate)
    ledger_id = await log_action(
        session=session,
        agent_name="p2_po",
        action_type="purchase_order_generated",
        entity_type="PurchaseOrder",
        entity_id=po.id,
        company_id=company_id,
        payload={
            "po_number": po_number,
            "indent_id": indent_id,
            "total_value_inr": str(indent.total_value_inr),
            "zoho_synced": zoho_synced,
            "email_sent": email_sent,
            "vendor_email": vendor_email or None,
        },
        autonomy_level="A2",
        requires_approval=False,
        agent_task_id=task.id if task else None,
    )
    po.action_ledger_id = ledger_id

    # Mark indent as po_raised
    indent.status = "po_raised"
    indent.updated_at = _utc_now()
    session.add(indent)

    session.commit()

    record_kpi(
        session=session,
        company_id=company_id,
        agent_name="p2_po",
        metric_name="po_value_inr",
        metric_value=float(indent.total_value_inr),
        entity_type="PurchaseOrder",
        entity_id=po.id,
    )

    return {
        "action": "generate_po",
        "po_id": po.id,
        "po_number": po_number,
        "zoho_synced": zoho_synced,
        "email_sent": email_sent,
        "total_value_inr": str(indent.total_value_inr),
    }


async def _flag_overdue(session: Session, task: AgentTask | None, company_id: int | None) -> dict:
    """Flag POs past expected_delivery_date and not yet delivered."""
    now = _utc_now()
    stmt = select(PurchaseOrder).where(
        PurchaseOrder.status.in_(["sent", "acknowledged", "partial_delivery"]),
        col(PurchaseOrder.expected_delivery_date) < now,
    )
    if company_id:
        stmt = stmt.where(PurchaseOrder.company_id == company_id)

    overdue_pos = session.exec(stmt).all()
    flagged: list[dict] = []

    for po in overdue_pos:
        days_overdue = (now - po.expected_delivery_date).days
        # Log overdue event (A1 — procurement manager must decide whether to escalate to vendor)
        await log_action(
            session=session,
            agent_name="p2_po",
            action_type="po_overdue_flagged",
            entity_type="PurchaseOrder",
            entity_id=po.id,
            company_id=po.company_id,
            payload={
                "po_number": po.po_number,
                "days_overdue": days_overdue,
                "expected_delivery_date": po.expected_delivery_date.isoformat(),
            },
            autonomy_level="A1",
            requires_approval=True,
            agent_task_id=task.id if task else None,
        )
        flagged.append({"po_id": po.id, "po_number": po.po_number, "days_overdue": days_overdue})
        logger.info("[P2] Flagged overdue PO %s (%d days)", po.po_number, days_overdue)

    session.commit()
    return {"action": "flag_overdue", "overdue_count": len(flagged), "flagged": flagged}


async def _cancel_po(session: Session, task: AgentTask | None, po_id: int | None, reason: str) -> dict:
    if not po_id:
        return {"error": "po_id required"}
    po = session.get(PurchaseOrder, po_id)
    if not po:
        return {"error": f"PO {po_id} not found"}
    if po.status in ("delivered", "cancelled"):
        return {"error": f"Cannot cancel PO in status {po.status!r}"}

    po.status = "cancelled"
    po.notes = reason or po.notes
    po.updated_at = _utc_now()
    session.add(po)
    session.commit()

    return {"cancelled": True, "po_id": po_id, "po_number": po.po_number}

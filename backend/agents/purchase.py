"""
Purchase Agent — Converts demand signals into purchase requests / PO drafts.

Escalates vendor delays and handles PO approvals.
This is a workflow/policy agent (no LLM calls). Invoked by the worker via
orchestrator.run_agent(agent_name="purchase", ...) when an AgentTask has
assigned_agent="purchase".
"""
from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session, select

from models.models import (
    AgentApproval,
    AgentTask,
    Interaction,
    Lead,
    Product,
    utc_now,
)

logger = logging.getLogger(__name__)

# Threshold (INR) above which a purchase request requires human approval
_APPROVAL_THRESHOLD_INR = 50_000

_VALID_ACTIONS = frozenset(
    ["create_purchase_request", "check_vendor_status", "escalate_delay", "approve_po"]
)


def _err(msg: str) -> dict:
    return {"status": "error", "error": msg}


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _create_purchase_request(session: Session, task: AgentTask, inp: dict) -> dict:
    lead_id = inp.get("lead_id")
    items: list[dict] = inp.get("items") or []

    if not items:
        return _err("items list is required for create_purchase_request")

    # Enrich items with product price for threshold check
    total_value = 0.0
    enriched_items = []
    for item in items:
        product_id = item.get("product_id")
        quantity = int(item.get("quantity") or 1)
        unit_price = float(item.get("unit_price") or 0)

        if product_id and unit_price == 0:
            product = session.exec(
                select(Product).where(
                    Product.id == product_id,
                    Product.company_id == task.company_id,
                )
            ).first()
            if product:
                unit_price = float(product.price or 0)

        line_total = unit_price * quantity
        total_value += line_total
        enriched_items.append(
            {
                "product_id": product_id,
                "quantity": quantity,
                "unit_price": unit_price,
                "required_by": item.get("required_by"),
                "line_total": line_total,
            }
        )

    requires_approval = total_value > _APPROVAL_THRESHOLD_INR

    # Store the request as output on this task (idempotent record)
    task.output_json = {
        "purchase_request": {
            "items": enriched_items,
            "total_value_inr": total_value,
            "requires_approval": requires_approval,
            "lead_id": lead_id,
        }
    }
    task.updated_at = utc_now()
    session.add(task)

    approval_id = None
    if requires_approval:
        lead_name = ""
        if lead_id:
            lead = session.exec(
                select(Lead).where(Lead.id == lead_id, Lead.company_id == task.company_id)
            ).first()
            if lead:
                lead_name = f" for {lead.name}"

        approval = AgentApproval(
            company_id=task.company_id,
            task_id=task.id,
            action_type="purchase_request_approval",
            action_summary=(
                f"Purchase request{lead_name}: {len(enriched_items)} item(s), "
                f"total INR {total_value:,.2f} (exceeds threshold)"
            ),
            action_payload={
                "lead_id": lead_id,
                "items": enriched_items,
                "total_value_inr": total_value,
            },
            status="pending",
            created_by=task.created_by,
            updated_by=task.created_by,
        )
        session.add(approval)
        session.commit()
        session.refresh(approval)
        approval_id = approval.id
    else:
        session.commit()

    return {
        "items": enriched_items,
        "total_value_inr": total_value,
        "requires_approval": requires_approval,
        "approval_id": approval_id,
        "lead_id": lead_id,
    }


def _check_vendor_status(session: Session, task: AgentTask, inp: dict) -> dict:
    vendor_id = inp.get("vendor_id")
    vendor_name: str | None = None

    # Resolve vendor by id or fall back to name-based account lookup
    if vendor_id:
        from models.models import Account
        account = session.exec(
            select(Account).where(
                Account.id == vendor_id,
                Account.company_id == task.company_id,
            )
        ).first()
        if account:
            vendor_name = account.name
            vendor_notes = account.notes
        else:
            vendor_name = f"vendor#{vendor_id}"
            vendor_notes = None
    else:
        vendor_name = inp.get("vendor_name")
        vendor_notes = None
        if vendor_name:
            from models.models import Account
            account = session.exec(
                select(Account).where(
                    Account.company_id == task.company_id,
                    Account.name == vendor_name,
                )
            ).first()
            if account:
                vendor_notes = account.notes
                vendor_id = account.id

    if not vendor_name:
        return _err("vendor_id or vendor_name is required for check_vendor_status")

    # Get last interaction for leads associated with this vendor account
    last_interaction = None
    last_interaction_date = None
    if vendor_id:
        interaction = session.exec(
            select(Interaction)
            .where(Interaction.company_id == task.company_id)
            .order_by(Interaction.started_at.desc())
            .limit(1)
        ).first()
        if interaction:
            last_interaction = interaction.content
            last_interaction_date = (
                interaction.started_at.isoformat() if interaction.started_at else None
            )

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "last_interaction_date": last_interaction_date,
        "last_interaction_notes": last_interaction,
        "vendor_notes": vendor_notes,
    }


def _escalate_delay(session: Session, task: AgentTask, inp: dict) -> dict:
    delay_days = inp.get("delay_days")
    po_id = inp.get("po_id")

    if delay_days is None:
        return _err("delay_days is required for escalate_delay")
    if not po_id:
        return _err("po_id is required for escalate_delay")

    approval = AgentApproval(
        company_id=task.company_id,
        task_id=task.id,
        action_type="vendor_delay_escalation",
        action_summary=f"Vendor delay {delay_days} days on PO {po_id}",
        action_payload={
            "po_id": po_id,
            "delay_days": delay_days,
            "vendor_id": inp.get("vendor_id"),
            "lead_id": inp.get("lead_id"),
        },
        status="pending",
        created_by=task.created_by,
        updated_by=task.created_by,
    )
    session.add(approval)
    session.commit()
    session.refresh(approval)

    return {
        "approval_id": approval.id,
        "action_type": "vendor_delay_escalation",
        "po_id": po_id,
        "delay_days": delay_days,
        "status": "pending",
    }


def _approve_po(session: Session, task: AgentTask, inp: dict) -> dict:
    """Approve a PO (automated if within threshold, else requires manual review)."""
    po_id = inp.get("po_id")
    if not po_id:
        return _err("po_id is required for approve_po")

    # Find the matching pending purchase_request_approval
    approval = session.exec(
        select(AgentApproval).where(
            AgentApproval.company_id == task.company_id,
            AgentApproval.action_type == "purchase_request_approval",
            AgentApproval.status == "pending",
        )
        .order_by(AgentApproval.created_at.desc())
    ).first()

    if not approval:
        # No pending approval — check if total is within threshold to auto-approve
        return {
            "po_id": po_id,
            "status": "auto_approved",
            "message": "No pending approval gate found; PO is within auto-approval threshold",
        }

    # Check total value from stored payload
    total_value = float(approval.action_payload.get("total_value_inr") or 0)
    if total_value <= _APPROVAL_THRESHOLD_INR:
        approval.status = "approved"
        approval.reviewed_at = utc_now()
        approval.reviewer_id = None
        approval.reviewer_note = f"Auto-approved by purchase agent (within INR {_APPROVAL_THRESHOLD_INR:,} threshold)"
        approval.updated_at = utc_now()
        approval.updated_by = task.created_by
        session.add(approval)
        session.commit()
        return {
            "po_id": po_id,
            "approval_id": approval.id,
            "status": "approved",
            "total_value_inr": total_value,
        }
    else:
        return {
            "po_id": po_id,
            "approval_id": approval.id,
            "status": "awaiting_manual_approval",
            "total_value_inr": total_value,
            "message": f"Total INR {total_value:,.2f} exceeds threshold; requires manual approval",
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(session: Session, task: AgentTask) -> dict:
    """
    Entry point called by the worker via orchestrator.run_agent.

    Args:
        session: Active SQLModel session.
        task:    The AgentTask record being processed. All input is read
                 from task.input_json.

    Returns:
        A JSON-serialisable dict written to AgentTask.output_json.
    """
    inp: dict[str, Any] = task.input_json or {}
    action = inp.get("action", "")

    if action not in _VALID_ACTIONS:
        return _err(
            f"Unknown action {action!r}. Valid: {sorted(_VALID_ACTIONS)}"
        )

    logger.info(
        "[PurchaseAgent] action=%s lead_id=%s company=%s",
        action, inp.get("lead_id"), task.company_id,
    )

    try:
        if action == "create_purchase_request":
            result = _create_purchase_request(session, task, inp)
        elif action == "check_vendor_status":
            result = _check_vendor_status(session, task, inp)
        elif action == "escalate_delay":
            result = _escalate_delay(session, task, inp)
        elif action == "approve_po":
            result = _approve_po(session, task, inp)
        else:
            result = _err(f"Unhandled action: {action!r}")
    except Exception as exc:
        logger.exception("[PurchaseAgent] action=%s failed: %s", action, exc)
        return _err(f"Purchase agent internal error: {exc}")

    return {"status": "ok", "action": action, "result": result}

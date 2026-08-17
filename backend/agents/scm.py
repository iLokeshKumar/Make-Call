"""
SCM Agent — Supply Chain Management.

Handles inventory allocation, dispatch scheduling, stock availability checks,
and SLA breach escalations.
This is a workflow/policy agent (no LLM calls). Invoked by the worker via
orchestrator.run_agent(agent_name="scm", ...) when an AgentTask has
assigned_agent="scm".
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from models.models import (
    AgentApproval,
    AgentTask,
    InstallationJob,
    Lead,
    Order,
    Product,
    utc_now,
)

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset(
    ["allocate_inventory", "schedule_dispatch", "check_availability", "escalate_sla_breach"]
)


def _err(msg: str) -> dict:
    return {"status": "error", "error": msg}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_product(session: Session, company_id: int, product_id: int) -> Product | None:
    return session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == company_id,
        )
    ).first()


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _allocate_inventory(session: Session, task: AgentTask, inp: dict) -> dict:
    items: list[dict] = inp.get("items") or []
    if not items:
        return _err("items list is required for allocate_inventory")

    allocation_results = []
    unavailable_items = []

    for item in items:
        product_id = item.get("product_id")
        requested_qty = int(item.get("quantity") or 1)

        if not product_id:
            allocation_results.append(
                {"product_id": None, "requested": requested_qty, "status": "error", "reason": "missing product_id"}
            )
            continue

        product = _get_product(session, task.company_id, product_id)
        if not product:
            allocation_results.append(
                {"product_id": product_id, "requested": requested_qty, "status": "not_found"}
            )
            unavailable_items.append({"product_id": product_id, "quantity": requested_qty, "reason": "product not found"})
            continue

        available_stock = product.stock if product.stock is not None else 0
        if available_stock >= requested_qty:
            # Decrement stock to reflect the soft-allocation
            product.stock = available_stock - requested_qty
            product.updated_at = utc_now()
            product.updated_by = task.created_by
            session.add(product)
            allocation_results.append(
                {
                    "product_id": product_id,
                    "product_name": product.name,
                    "requested": requested_qty,
                    "allocated": requested_qty,
                    "remaining_stock": product.stock,
                    "status": "allocated",
                }
            )
        else:
            allocation_results.append(
                {
                    "product_id": product_id,
                    "product_name": product.name,
                    "requested": requested_qty,
                    "allocated": 0,
                    "available": available_stock,
                    "status": "insufficient_stock",
                }
            )
            unavailable_items.append(
                {
                    "product_id": product_id,
                    "quantity": requested_qty,
                    "available": available_stock,
                    "reason": "insufficient_stock",
                }
            )

    approval_id = None
    if unavailable_items:
        approval = AgentApproval(
            company_id=task.company_id,
            task_id=task.id,
            action_type="inventory_shortage",
            action_summary=(
                f"{len(unavailable_items)} item(s) unavailable for allocation; "
                "manual handling required"
            ),
            action_payload={
                "unavailable_items": unavailable_items,
                "lead_id": inp.get("lead_id"),
                "order_id": inp.get("order_id"),
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
        "allocation_results": allocation_results,
        "fully_allocated": len(unavailable_items) == 0,
        "approval_id": approval_id,
    }


def _schedule_dispatch(session: Session, task: AgentTask, inp: dict) -> dict:
    order_id = inp.get("order_id")
    lead_id = inp.get("lead_id")
    dispatch_date_str = inp.get("dispatch_date")

    if not dispatch_date_str:
        return _err("dispatch_date is required for schedule_dispatch")

    try:
        dispatch_dt = datetime.fromisoformat(dispatch_date_str)
        if dispatch_dt.tzinfo is None:
            dispatch_dt = dispatch_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return _err(f"Invalid dispatch_date format: {dispatch_date_str!r}. Use ISO 8601.")

    # If an order_id is provided, update the order and optionally create an InstallationJob
    if order_id:
        order = session.exec(
            select(Order).where(Order.id == order_id, Order.company_id == task.company_id)
        ).first()
        if not order:
            return _err(f"Order {order_id} not found")

        order.status = "processing"
        order.expected_delivery_at = dispatch_dt
        order.updated_at = utc_now()
        order.updated_by = task.created_by
        session.add(order)

        resolved_lead_id = lead_id or order.lead_id
        items: list[dict] = inp.get("items") or []
        needs_installation = _check_needs_installation(session, task.company_id, items)

        install_job_id = None
        if needs_installation and resolved_lead_id:
            job_number = f"JOB-{uuid.uuid4().hex[:8].upper()}"
            job = InstallationJob(
                company_id=task.company_id,
                order_id=order_id,
                lead_id=resolved_lead_id,
                job_number=job_number,
                status="scheduled",
                scheduled_at=dispatch_dt,
                created_by=task.created_by,
                updated_by=task.created_by,
            )
            session.add(job)
            session.flush()
            install_job_id = job.id

        session.commit()

        return {
            "order_id": order_id,
            "lead_id": resolved_lead_id,
            "dispatch_date": dispatch_dt.isoformat(),
            "order_status": "processing",
            "installation_job_id": install_job_id,
        }
    else:
        # No order yet — just return a scheduling confirmation (no-op on DB)
        return {
            "order_id": None,
            "lead_id": lead_id,
            "dispatch_date": dispatch_dt.isoformat(),
            "message": "Dispatch date noted. Provide order_id to update order status.",
        }


def _check_needs_installation(session: Session, company_id: int, items: list[dict]) -> bool:
    """Return True if any product in items has installation-related attributes."""
    for item in items:
        product_id = item.get("product_id")
        if not product_id:
            continue
        product = _get_product(session, company_id, product_id)
        if product and product.attributes:
            attrs = product.attributes
            if attrs.get("requires_installation") or attrs.get("installation_required"):
                return True
    return False


def _check_availability(session: Session, task: AgentTask, inp: dict) -> dict:
    items: list[dict] = inp.get("items") or []
    if not items:
        return _err("items list is required for check_availability")

    availability = []
    for item in items:
        product_id = item.get("product_id")
        requested_qty = int(item.get("quantity") or 1)

        if not product_id:
            availability.append(
                {"product_id": None, "quantity_requested": requested_qty, "stock": "unknown", "reason": "missing product_id"}
            )
            continue

        product = _get_product(session, task.company_id, product_id)
        if not product:
            availability.append(
                {"product_id": product_id, "quantity_requested": requested_qty, "stock": "unknown", "reason": "product not found"}
            )
            continue

        stock = product.stock if product.stock is not None else "unknown"
        available = stock != "unknown" and int(stock) >= requested_qty
        availability.append(
            {
                "product_id": product_id,
                "product_name": product.name,
                "sku": product.sku,
                "quantity_requested": requested_qty,
                "stock": stock,
                "is_available": available,
            }
        )

    return {"availability": availability}


def _escalate_sla_breach(session: Session, task: AgentTask, inp: dict) -> dict:
    order_id = inp.get("order_id")
    lead_id = inp.get("lead_id")
    items: list[dict] = inp.get("items") or []

    summary_parts = []
    if order_id:
        summary_parts.append(f"Order #{order_id}")
    if lead_id:
        summary_parts.append(f"Lead #{lead_id}")
    if items:
        product_ids = [str(i.get("product_id", "?")) for i in items]
        summary_parts.append(f"Products: {', '.join(product_ids)}")

    action_summary = "SLA breach: " + ("; ".join(summary_parts) if summary_parts else "dispatch overdue")

    approval = AgentApproval(
        company_id=task.company_id,
        task_id=task.id,
        action_type="sla_breach",
        action_summary=action_summary,
        action_payload={
            "order_id": order_id,
            "lead_id": lead_id,
            "items": items,
            "warehouse_id": inp.get("warehouse_id"),
            "dispatch_date": inp.get("dispatch_date"),
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
        "action_type": "sla_breach",
        "action_summary": action_summary,
        "status": "pending",
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
        "[SCMAgent] action=%s order_id=%s company=%s",
        action, inp.get("order_id"), task.company_id,
    )

    try:
        if action == "allocate_inventory":
            result = _allocate_inventory(session, task, inp)
        elif action == "schedule_dispatch":
            result = _schedule_dispatch(session, task, inp)
        elif action == "check_availability":
            result = _check_availability(session, task, inp)
        elif action == "escalate_sla_breach":
            result = _escalate_sla_breach(session, task, inp)
        else:
            result = _err(f"Unhandled action: {action!r}")
    except Exception as exc:
        logger.exception("[SCMAgent] action=%s failed: %s", action, exc)
        return _err(f"SCM agent internal error: {exc}")

    return {"status": "ok", "action": action, "result": result}

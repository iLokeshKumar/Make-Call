"""
Finance Agent — Auto invoices, payment links, reminders, dispute handling.

Actions:
  generate_invoice  — Create Invoice from an Order; flags approval if amount > 500000
  send_payment_link — Attach placeholder payment link and log WhatsApp interaction
  send_reminder     — Create email reminder Interactions for overdue invoices
  handle_dispute    — Create AgentApproval and mark invoice as disputed
  write_off         — Write off invoice if task carries approved=True
  check_overdue     — Mark sent invoices past due_date as overdue; return count
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from models.models import (
    AgentApproval,
    AgentTask,
    Interaction,
    Invoice,
    Order,
    utc_now,
)

logger = logging.getLogger(__name__)

_APPROVAL_THRESHOLD = 500_000  # INR — invoices above this require approval


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_invoice_number(session: Session, company_id: int) -> str:
    current_year = datetime.now(timezone.utc).year
    prefix = f"INV-{current_year}-"
    invoices = session.exec(
        select(Invoice).where(Invoice.company_id == company_id)
    ).all()
    max_seq = 0
    for inv in invoices:
        if inv.invoice_number.startswith(prefix):
            try:
                seq = int(inv.invoice_number[len(prefix):])
                max_seq = max(max_seq, seq)
            except ValueError:
                pass
    return f"{prefix}{max_seq + 1:04d}"


def _get_invoice(session: Session, company_id: int, invoice_id: int) -> Invoice | None:
    return session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.company_id == company_id,
        )
    ).first()


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_generate_invoice(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    order_id = inp.get("order_id")
    if not order_id:
        return {"error": "order_id is required for generate_invoice"}

    order = session.exec(
        select(Order).where(
            Order.id == order_id,
            Order.company_id == task.company_id,
        )
    ).first()
    if not order:
        return {"error": f"Order {order_id} not found"}

    requires_approval = float(order.total_amount) > _APPROVAL_THRESHOLD

    invoice = Invoice(
        company_id=task.company_id,
        order_id=order.id,
        lead_id=order.lead_id,
        account_id=order.account_id,
        owner_user_id=order.owner_user_id,
        invoice_number=_generate_invoice_number(session, task.company_id),
        status="draft",
        currency=order.currency,
        subtotal=order.subtotal,
        discount_amount=order.discount_amount,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        amount_due=order.total_amount,
        requires_approval=requires_approval,
    )
    session.add(invoice)
    session.commit()
    session.refresh(invoice)

    logger.info(
        "[FinanceAgent] Generated invoice %s for order %s (requires_approval=%s)",
        invoice.invoice_number, order_id, requires_approval,
    )
    return {
        "action": "generate_invoice",
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "total_amount": float(invoice.total_amount),
        "requires_approval": requires_approval,
        "status": invoice.status,
    }


def _handle_send_payment_link(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    invoice_id = inp.get("invoice_id")
    if not invoice_id:
        return {"error": "invoice_id is required for send_payment_link"}

    invoice = _get_invoice(session, task.company_id, invoice_id)
    if not invoice:
        return {"error": f"Invoice {invoice_id} not found"}

    if invoice.status not in ("draft", "sent", "partially_paid"):
        return {
            "error": f"Cannot send payment link for invoice in status '{invoice.status}'",
            "invoice_id": invoice_id,
        }

    payment_link = f"https://pay.example.com/{invoice.invoice_number}"
    invoice.payment_link = payment_link
    session.add(invoice)

    interaction = Interaction(
        company_id=task.company_id,
        lead_id=invoice.lead_id,
        type="payment_link",
        channel="whatsapp",
        direction="outbound",
        source="finance_agent",
        content=f"Payment link for invoice {invoice.invoice_number}: {payment_link}",
        started_at=utc_now(),
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)

    logger.info(
        "[FinanceAgent] Payment link sent for invoice %s (interaction %s)",
        invoice.invoice_number, interaction.id,
    )
    return {
        "action": "send_payment_link",
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "payment_link": payment_link,
        "interaction_id": interaction.id,
    }


def _handle_send_reminder(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    lead_id = inp.get("lead_id")
    invoice_id = inp.get("invoice_id")
    now = utc_now()

    if invoice_id:
        invoices = session.exec(
            select(Invoice).where(
                Invoice.id == invoice_id,
                Invoice.company_id == task.company_id,
            )
        ).all()
    elif lead_id:
        invoices = session.exec(
            select(Invoice).where(
                Invoice.lead_id == lead_id,
                Invoice.company_id == task.company_id,
                Invoice.status.in_(("sent", "overdue", "partially_paid")),
            )
        ).all()
    else:
        return {"error": "invoice_id or lead_id is required for send_reminder"}

    count = 0
    for inv in invoices:
        content = (
            f"Reminder: Invoice {inv.invoice_number} for amount {inv.currency} "
            f"{float(inv.amount_due):.2f} is due. Please arrange payment at your earliest convenience."
        )
        interaction = Interaction(
            company_id=task.company_id,
            lead_id=inv.lead_id,
            type="payment_reminder",
            channel="email",
            direction="outbound",
            source="finance_agent",
            content=content,
            started_at=now,
        )
        session.add(interaction)
        count += 1

    if count:
        session.commit()

    logger.info("[FinanceAgent] Sent %d payment reminder(s)", count)
    return {
        "action": "send_reminder",
        "reminders_sent": count,
    }


def _handle_handle_dispute(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    invoice_id = inp.get("invoice_id")
    dispute_reason = inp.get("dispute_reason", "")

    if not invoice_id:
        return {"error": "invoice_id is required for handle_dispute"}

    invoice = _get_invoice(session, task.company_id, invoice_id)
    if not invoice:
        return {"error": f"Invoice {invoice_id} not found"}

    # Mark in notes
    dispute_note = f"[DISPUTED]: {dispute_reason}"
    invoice.notes = (invoice.notes + "\n" + dispute_note).strip() if invoice.notes else dispute_note
    session.add(invoice)

    # Create approval record
    approval = AgentApproval(
        company_id=task.company_id,
        task_id=task.id,
        action_type="invoice_dispute",
        action_summary=f"Dispute on invoice {invoice_id}: {dispute_reason}",
        action_payload={"invoice_id": invoice_id, "dispute_reason": dispute_reason},
        status="pending",
    )
    session.add(approval)
    session.commit()
    session.refresh(approval)

    logger.info(
        "[FinanceAgent] Dispute created for invoice %s (approval %s)",
        invoice_id, approval.id,
    )
    return {
        "action": "handle_dispute",
        "invoice_id": invoice_id,
        "approval_id": approval.id,
        "status": "pending_approval",
    }


def _handle_write_off(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    invoice_id = inp.get("invoice_id")
    write_off_reason = inp.get("write_off_reason", "")
    approved = inp.get("approved", False)

    if not invoice_id:
        return {"error": "invoice_id is required for write_off"}

    if not approved:
        # Create an approval request and halt
        approval = AgentApproval(
            company_id=task.company_id,
            task_id=task.id,
            action_type="invoice_write_off",
            action_summary=f"Write-off request for invoice {invoice_id}: {write_off_reason}",
            action_payload={"invoice_id": invoice_id, "write_off_reason": write_off_reason},
            status="pending",
        )
        session.add(approval)
        session.commit()
        session.refresh(approval)
        logger.info("[FinanceAgent] Write-off approval requested for invoice %s", invoice_id)
        return {
            "action": "write_off",
            "invoice_id": invoice_id,
            "approval_id": approval.id,
            "status": "awaiting_approval",
        }

    # Approved — proceed with write-off
    invoice = _get_invoice(session, task.company_id, invoice_id)
    if not invoice:
        return {"error": f"Invoice {invoice_id} not found"}

    write_off_note = f"[WRITTEN_OFF]: {write_off_reason}"
    invoice.notes = (invoice.notes + "\n" + write_off_note).strip() if invoice.notes else write_off_note
    session.add(invoice)
    session.commit()

    logger.info("[FinanceAgent] Invoice %s written off", invoice_id)
    return {
        "action": "write_off",
        "invoice_id": invoice_id,
        "status": "written_off",
    }


def _handle_check_overdue(session: Session, task: AgentTask) -> dict:
    now = utc_now()
    overdue_invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == task.company_id,
            Invoice.status == "sent",
            Invoice.due_date <= now,
        )
    ).all()

    count = 0
    for inv in overdue_invoices:
        inv.status = "overdue"
        inv.overdue_at = now
        session.add(inv)
        count += 1

    if count:
        session.commit()

    logger.info("[FinanceAgent] Marked %d invoices as overdue", count)
    return {
        "action": "check_overdue",
        "overdue_count": count,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(session: Session, task: AgentTask) -> dict:
    """Dispatch to the appropriate finance agent action."""
    action = task.input_json.get("action")
    try:
        if action == "generate_invoice":
            return _handle_generate_invoice(session, task)
        elif action == "send_payment_link":
            return _handle_send_payment_link(session, task)
        elif action == "send_reminder":
            return _handle_send_reminder(session, task)
        elif action == "handle_dispute":
            return _handle_handle_dispute(session, task)
        elif action == "write_off":
            return _handle_write_off(session, task)
        elif action == "check_overdue":
            return _handle_check_overdue(session, task)
        else:
            return {
                "error": f"Unknown action: {action!r}",
                "valid_actions": [
                    "generate_invoice", "send_payment_link", "send_reminder",
                    "handle_dispute", "write_off", "check_overdue",
                ],
            }
    except Exception as exc:
        logger.exception("[FinanceAgent] action=%s failed: %s", action, exc)
        return {"error": str(exc), "action": action}

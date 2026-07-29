"""
F1 Collections Agent — Dealer AR dunning with behavior-scored dunning ladder.

Scans overdue invoices every morning, scores each dealer by payment behavior,
selects the right dunning tier, drafts WhatsApp/email message, and writes
ActionLedger proposals for Finance Manager batch review.

Actions
-------
daily_scan      Morning AR scan. Writes ActionLedger proposals; returns summary.
send_dunning    Execute one approved dunning action (send WhatsApp/email).
record_payment  Log a received payment and knock off the invoice amount.

Autonomy
--------
Tiers 1-3  (1–14 days overdue) : A2 — batch-reviewed by Finance Manager.
Tiers 4-5  (15+ days overdue)  : A1 — individual approval, never batch.

Dunning Ladder
--------------
Tier 1  1–3 d   Gentle WhatsApp reminder.
Tier 2  4–7 d   Firmer WhatsApp + email.
Tier 3  8–14 d  Urgent WhatsApp with payment link.
Tier 4  15–29 d Escalation: Branch Head notified. A1.
Tier 5  30 d+   Legal notice draft prepared. A1. Always individual review.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models.models import (
    AgentTask,
    Interaction,
    Invoice,
    Lead,
    Payment,
    utc_now,
)
from services.action_ledger import log_action, record_kpi

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dunning ladder policy
# ---------------------------------------------------------------------------

_DUNNING_TIERS: list[dict] = [
    {
        "tier": 1,
        "overdue_days_min": 1,
        "overdue_days_max": 3,
        "autonomy_level": "A2",
        "channels": ["whatsapp"],
        "tone": "gentle",
        "subject": None,
    },
    {
        "tier": 2,
        "overdue_days_min": 4,
        "overdue_days_max": 7,
        "autonomy_level": "A2",
        "channels": ["whatsapp", "email"],
        "tone": "firm",
        "subject": "Action Required: Outstanding Invoice {invoice_number}",
    },
    {
        "tier": 3,
        "overdue_days_min": 8,
        "overdue_days_max": 14,
        "autonomy_level": "A2",
        "channels": ["whatsapp", "email"],
        "tone": "urgent",
        "subject": "URGENT: Invoice {invoice_number} Overdue — Immediate Payment Required",
    },
    {
        "tier": 4,
        "overdue_days_min": 15,
        "overdue_days_max": 29,
        "autonomy_level": "A1",
        "channels": ["whatsapp", "email"],
        "tone": "escalation",
        "subject": "Escalation Notice: Invoice {invoice_number} — {overdue_days} Days Overdue",
    },
    {
        "tier": 5,
        "overdue_days_min": 30,
        "overdue_days_max": 9999,
        "autonomy_level": "A1",
        "channels": ["email"],
        "tone": "legal",
        "subject": "Legal Notice: Invoice {invoice_number} — Immediate Settlement Required",
    },
]


def _get_tier(overdue_days: int) -> dict:
    for tier in _DUNNING_TIERS:
        if tier["overdue_days_min"] <= overdue_days <= tier["overdue_days_max"]:
            return tier
    return _DUNNING_TIERS[-1]


# ---------------------------------------------------------------------------
# Message drafting
# ---------------------------------------------------------------------------

_MESSAGES: dict[str, str] = {
    "gentle": (
        "Hi {name}, this is a friendly reminder that invoice {invoice_number} "
        "for ₹{amount_due:,.0f} was due on {due_date}. "
        "Please arrange payment at your earliest convenience. "
        "Reply here or call us if you have any questions."
    ),
    "firm": (
        "Dear {name}, invoice {invoice_number} for ₹{amount_due:,.0f} "
        "is now {overdue_days} day(s) overdue (due {due_date}). "
        "Kindly arrange payment to avoid late charges. "
        "{payment_link_line}"
        "Contact us immediately if there is a dispute."
    ),
    "urgent": (
        "Dear {name}, URGENT NOTICE — invoice {invoice_number} for ₹{amount_due:,.0f} "
        "is {overdue_days} days overdue. "
        "Immediate payment is required to avoid service disruption. "
        "{payment_link_line}"
        "Call your Yexis account manager now if you need assistance."
    ),
    "escalation": (
        "Dear {name}, this is a formal notice that invoice {invoice_number} "
        "for ₹{amount_due:,.0f} remains unpaid after {overdue_days} days. "
        "This matter has been escalated to our Branch Head. "
        "Please settle the outstanding amount within 48 hours or contact us immediately "
        "to agree a payment plan."
    ),
    "legal": (
        "Dear {name}, LEGAL NOTICE — Invoice {invoice_number} for ₹{amount_due:,.0f} "
        "has been outstanding for {overdue_days} days despite prior reminders. "
        "Yexis Electronics reserves the right to initiate legal proceedings for recovery "
        "if payment is not received within 7 days from this notice. "
        "Settle immediately to avoid further action."
    ),
}


def _draft_message(tone: str, lead: Lead, invoice: Invoice, overdue_days: int) -> str:
    payment_link_line = (
        f"Pay now: {invoice.payment_link}  " if invoice.payment_link else ""
    )
    due_date_str = (
        invoice.due_date.strftime("%d %b %Y") if invoice.due_date else "N/A"
    )
    template = _MESSAGES[tone]
    return template.format(
        name=lead.name,
        invoice_number=invoice.invoice_number,
        amount_due=float(invoice.amount_due),
        due_date=due_date_str,
        overdue_days=overdue_days,
        payment_link_line=payment_link_line,
    )


# ---------------------------------------------------------------------------
# Behavior scoring
# ---------------------------------------------------------------------------

def _payment_behavior_score(
    session: Session,
    company_id: int,
    lead_id: int,
    lookback_days: int = 365,
) -> dict:
    """Return simple payment behavior stats for a dealer.

    Returns:
        {
            "total_invoices": int,
            "paid_on_time": int,
            "paid_late": int,
            "still_unpaid": int,
            "late_rate_pct": float,   # 0-100; higher = worse payer
        }
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == company_id,
            Invoice.lead_id == lead_id,
            Invoice.created_at >= cutoff,
        )
    ).all()

    paid_on_time = 0
    paid_late = 0
    still_unpaid = 0

    for inv in invoices:
        if inv.paid_at is None:
            still_unpaid += 1
        elif inv.due_date and inv.paid_at > inv.due_date:
            paid_late += 1
        else:
            paid_on_time += 1

    total = len(invoices)
    late_rate = round((paid_late / total * 100) if total else 0, 1)

    return {
        "total_invoices": total,
        "paid_on_time": paid_on_time,
        "paid_late": paid_late,
        "still_unpaid": still_unpaid,
        "late_rate_pct": late_rate,
    }


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_daily_scan(session: Session, task: AgentTask) -> dict:
    """Scan all overdue invoices and create ActionLedger proposals.

    One proposal is created per (lead, dunning_tier) group — not per invoice —
    so the Finance Manager sees one line per dealer, not one per invoice.
    If a dealer has 3 overdue invoices we propose one consolidated message.
    """
    now = datetime.now(timezone.utc)
    company_id = task.company_id

    # Fetch all unpaid invoices with a past due_date
    overdue_invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == company_id,
            Invoice.status.in_(["sent", "overdue", "partially_paid"]),
            Invoice.due_date <= now,
        )
    ).all()

    if not overdue_invoices:
        logger.info("[F1] daily_scan: no overdue invoices for company %d", company_id)
        return {"action": "daily_scan", "proposals_created": 0, "dealers_scanned": 0}

    # Mark any "sent" invoices that are now overdue
    newly_overdue = 0
    for inv in overdue_invoices:
        if inv.status == "sent":
            inv.status = "overdue"
            inv.overdue_at = now
            session.add(inv)
            newly_overdue += 1
    if newly_overdue:
        session.flush()

    # Group by lead_id: pick worst-case invoice (most overdue) per dealer
    dealer_map: dict[int, dict] = {}
    for inv in overdue_invoices:
        if inv.due_date is None:
            continue
        overdue_days = max(0, (now - inv.due_date).days)
        lead_id = inv.lead_id
        if lead_id not in dealer_map:
            dealer_map[lead_id] = {
                "invoices": [],
                "max_overdue_days": 0,
                "total_amount_due": Decimal("0"),
            }
        dealer_map[lead_id]["invoices"].append(inv)
        dealer_map[lead_id]["total_amount_due"] += inv.amount_due
        dealer_map[lead_id]["max_overdue_days"] = max(
            dealer_map[lead_id]["max_overdue_days"], overdue_days
        )

    proposals_created = 0
    proposals: list[dict] = []

    for lead_id, data in dealer_map.items():
        lead = session.get(Lead, lead_id)
        if not lead:
            continue

        overdue_days = data["max_overdue_days"]
        total_due = data["total_amount_due"]
        tier_config = _get_tier(overdue_days)

        # Use the most-overdue invoice as the primary reference
        primary_invoice = max(
            data["invoices"],
            key=lambda i: (now - i.due_date).days if i.due_date else 0,
        )

        behavior = _payment_behavior_score(session, company_id, lead_id)
        message_text = _draft_message(
            tier_config["tone"], lead, primary_invoice, overdue_days
        )

        invoice_refs = [i.invoice_number for i in data["invoices"]]
        input_snapshot = {
            "lead_id": lead_id,
            "dealer_name": lead.name,
            "dealer_phone": lead.normalized_phone,
            "overdue_days": overdue_days,
            "total_amount_due_inr": float(total_due),
            "invoice_count": len(data["invoices"]),
            "invoice_numbers": invoice_refs,
            "primary_invoice_id": primary_invoice.id,
            "payment_behavior": behavior,
            "dunning_tier": tier_config["tier"],
            "channels": tier_config["channels"],
        }
        output_snapshot = {
            "message_draft": message_text,
            "autonomy_level": tier_config["autonomy_level"],
            "channels": tier_config["channels"],
            "email_subject": (
                tier_config["subject"].format(
                    invoice_number=primary_invoice.invoice_number,
                    overdue_days=overdue_days,
                ) if tier_config["subject"] else None
            ),
        }
        rationale = (
            f"Dealer '{lead.name}' has {len(data['invoices'])} overdue invoice(s) "
            f"totalling ₹{float(total_due):,.0f}. Max overdue: {overdue_days} days. "
            f"Dunning tier {tier_config['tier']} ({tier_config['tone']}). "
            f"Late payment rate (12m): {behavior['late_rate_pct']}%."
        )

        ledger_entry = log_action(
            session=session,
            company_id=company_id,
            agent_name="f1_collections",
            action_type="send_dunning_message",
            autonomy_level=tier_config["autonomy_level"],
            input_data=input_snapshot,
            output_data=output_snapshot,
            rationale=rationale,
            agent_task_id=task.id,
            entity_type="lead",
            entity_id=lead_id,
            status="proposed",
        )

        proposals_created += 1
        proposals.append({
            "ledger_id": ledger_entry.id,
            "dealer_name": lead.name,
            "overdue_days": overdue_days,
            "total_amount_due_inr": float(total_due),
            "dunning_tier": tier_config["tier"],
            "autonomy_level": tier_config["autonomy_level"],
            "channels": tier_config["channels"],
        })

    session.flush()

    record_kpi(
        session=session,
        company_id=company_id,
        agent_name="f1_collections",
        metric_name="daily_scan_dealers_overdue",
        metric_value=len(dealer_map),
        metadata={"proposals_created": proposals_created, "newly_overdue_invoices": newly_overdue},
    )

    logger.info(
        "[F1] daily_scan: company=%d dealers=%d proposals=%d",
        company_id, len(dealer_map), proposals_created,
    )
    return {
        "action": "daily_scan",
        "dealers_scanned": len(dealer_map),
        "proposals_created": proposals_created,
        "newly_overdue_invoices": newly_overdue,
        "proposals": proposals,
    }


def _handle_send_dunning(session: Session, task: AgentTask) -> dict:
    """Execute an approved dunning action.

    Called by the automation worker after a Finance Manager approves a
    ActionLedger entry. Sends the WhatsApp/email and logs the interaction.

    Required input_json fields:
        ledger_id       — ActionLedger.id of the approved proposal
        approved_by     — user_id of the reviewer
    """
    from services.action_ledger import complete_action, fail_action
    from models.models import ActionLedger

    inp = task.input_json
    ledger_id = inp.get("ledger_id")
    if not ledger_id:
        return {"error": "ledger_id is required for send_dunning"}

    ledger_entry = session.get(ActionLedger, ledger_id)
    if not ledger_entry:
        return {"error": f"ActionLedger entry {ledger_id} not found"}
    if ledger_entry.status not in ("approved",):
        return {
            "error": f"Entry {ledger_id} is in status '{ledger_entry.status}', expected 'approved'",
        }

    snap = ledger_entry.input_snapshot
    out = ledger_entry.output_snapshot
    lead_id = snap.get("lead_id")
    lead = session.get(Lead, lead_id) if lead_id else None
    if not lead:
        fail_action(session, ledger_id, "Lead not found at execution time")
        return {"error": f"Lead {lead_id} not found"}

    channels: list[str] = out.get("channels", ["whatsapp"])
    message_text: str = out.get("message_draft", "")
    email_subject: Optional[str] = out.get("email_subject")
    sent_channels: list[str] = []
    errors: list[str] = []

    # --- WhatsApp ---
    if "whatsapp" in channels and lead.normalized_phone:
        try:
            from whatsapp_service import send_whatsapp_message
            result = send_whatsapp_message(
                to_phone=lead.normalized_phone,
                body=message_text,
                session=session,
                company_id=task.company_id,
                lead_id=lead_id,
            )
            if result.get("success"):
                sent_channels.append("whatsapp")
                _log_interaction(
                    session, task.company_id, lead_id,
                    channel="whatsapp",
                    content=message_text,
                    metadata={"whatsapp_sid": result.get("message_sid")},
                )
            else:
                errors.append(f"whatsapp: {result}")
        except Exception as exc:
            logger.exception("[F1] WhatsApp send failed for lead %d", lead_id)
            errors.append(f"whatsapp: {exc}")

    # --- Email ---
    if "email" in channels and lead.email:
        try:
            from email_service import send_email
            send_email(
                to_email=lead.email,
                subject=email_subject or "Outstanding Invoice — Yexis Electronics",
                body=message_text,
            )
            sent_channels.append("email")
            _log_interaction(
                session, task.company_id, lead_id,
                channel="email",
                content=message_text,
                metadata={"subject": email_subject},
            )
        except Exception as exc:
            logger.exception("[F1] Email send failed for lead %d", lead_id)
            errors.append(f"email: {exc}")

    if not sent_channels and errors:
        fail_action(session, ledger_id, "; ".join(errors))
        return {"error": "All channels failed", "details": errors}

    complete_action(
        session, ledger_id,
        executed_result={"sent_channels": sent_channels, "errors": errors},
    )

    record_kpi(
        session=session,
        company_id=task.company_id,
        agent_name="f1_collections",
        metric_name="dunning_messages_sent",
        metric_value=len(sent_channels),
        entity_type="lead",
        entity_id=lead_id,
        action_ledger_id=ledger_id,
        metadata={"tier": snap.get("dunning_tier"), "channels": sent_channels},
    )

    logger.info(
        "[F1] send_dunning: lead=%d ledger=%d channels=%s",
        lead_id, ledger_id, sent_channels,
    )
    return {
        "action": "send_dunning",
        "ledger_id": ledger_id,
        "lead_id": lead_id,
        "sent_channels": sent_channels,
        "errors": errors,
    }


def _handle_record_payment(session: Session, task: AgentTask) -> dict:
    """Record a payment received and knock it off the invoice.

    Required input_json:
        invoice_id      — Invoice to knock off
        amount_inr      — Amount received
        reference       — Bank/UPI reference number
        payment_method  — "bank_transfer" | "upi" | "cheque" | "neft" | "rtgs"
        payment_date    — ISO date string (defaults to now)
    """
    inp = task.input_json
    invoice_id = inp.get("invoice_id")
    amount_inr = inp.get("amount_inr")
    reference = inp.get("reference", "")
    payment_method = inp.get("payment_method", "bank_transfer")
    payment_date_str = inp.get("payment_date")

    if not invoice_id or amount_inr is None:
        return {"error": "invoice_id and amount_inr are required for record_payment"}

    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.company_id == task.company_id,
        )
    ).first()
    if not invoice:
        return {"error": f"Invoice {invoice_id} not found"}
    if invoice.status in ("paid", "cancelled", "written_off"):
        return {"error": f"Invoice {invoice_id} is already in status '{invoice.status}'"}

    payment_dt = (
        datetime.fromisoformat(payment_date_str).replace(tzinfo=timezone.utc)
        if payment_date_str
        else datetime.now(timezone.utc)
    )
    amount = Decimal(str(amount_inr))

    payment = Payment(
        company_id=task.company_id,
        invoice_id=invoice.id,
        lead_id=invoice.lead_id,
        amount=amount,
        currency=invoice.currency,
        status="captured",
        payment_method=payment_method,
        reference_number=reference or None,
        captured_at=payment_dt,
        notes=f"Recorded by F1 Collections agent. Ref: {reference}",
    )
    session.add(payment)

    # Knock off invoice
    invoice.amount_paid += amount
    invoice.amount_due = max(Decimal("0"), invoice.amount_due - amount)
    if invoice.amount_due <= Decimal("0.01"):
        invoice.status = "paid"
        invoice.paid_at = payment_dt
    elif invoice.amount_paid > Decimal("0"):
        invoice.status = "partially_paid"
    session.add(invoice)
    session.flush()

    # Log to action ledger
    ledger_entry = log_action(
        session=session,
        company_id=task.company_id,
        agent_name="f1_collections",
        action_type="record_payment_knockoff",
        autonomy_level="A2",
        input_data={
            "invoice_id": invoice_id,
            "invoice_number": invoice.invoice_number,
            "amount_inr": float(amount),
            "reference": reference,
            "payment_method": payment_method,
        },
        output_data={
            "new_status": invoice.status,
            "amount_paid_total": float(invoice.amount_paid),
            "amount_due_remaining": float(invoice.amount_due),
        },
        rationale=f"Payment of ₹{float(amount):,.0f} received via {payment_method}. Ref: {reference}.",
        agent_task_id=task.id,
        entity_type="invoice",
        entity_id=invoice.id,
        status="auto_executed",
    )

    record_kpi(
        session=session,
        company_id=task.company_id,
        agent_name="f1_collections",
        metric_name="payment_collected_inr",
        metric_value=float(amount),
        entity_type="lead",
        entity_id=invoice.lead_id,
        action_ledger_id=ledger_entry.id,
    )

    logger.info(
        "[F1] record_payment: invoice=%s amount=₹%.0f status=%s",
        invoice.invoice_number, float(amount), invoice.status,
    )
    return {
        "action": "record_payment",
        "invoice_id": invoice_id,
        "invoice_number": invoice.invoice_number,
        "amount_recorded_inr": float(amount),
        "invoice_status": invoice.status,
        "amount_due_remaining_inr": float(invoice.amount_due),
        "payment_id": payment.id,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_interaction(
    session: Session,
    company_id: int,
    lead_id: int,
    channel: str,
    content: str,
    metadata: Optional[dict] = None,
) -> Interaction:
    interaction = Interaction(
        company_id=company_id,
        lead_id=lead_id,
        type="payment_reminder",
        channel=channel,
        direction="outbound",
        source="f1_collections",
        content=content,
        metadata_json=metadata or {},
        started_at=utc_now(),
    )
    session.add(interaction)
    return interaction


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

_VALID_ACTIONS = frozenset(["daily_scan", "send_dunning", "record_payment"])


async def run(session: Session, task: AgentTask) -> dict:
    """Dispatch to the appropriate F1 action."""
    action = task.input_json.get("action")
    if action not in _VALID_ACTIONS:
        return {
            "error": f"Unknown action: {action!r}",
            "valid_actions": sorted(_VALID_ACTIONS),
        }
    try:
        if action == "daily_scan":
            return _handle_daily_scan(session, task)
        elif action == "send_dunning":
            return _handle_send_dunning(session, task)
        elif action == "record_payment":
            return _handle_record_payment(session, task)
    except Exception as exc:
        logger.exception("[F1] action=%s failed: %s", action, exc)
        return {"error": str(exc), "action": action}

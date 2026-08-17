"""Action Ledger service — the single write path for all agent action records.

Every agent calls log_action() once per atomic action. This is the audit trail
that powers the monthly assurance review, autonomy promotion gates, and the
D1 dashboard KPI feeds.

Usage (inside any agent):
    from services.action_ledger import log_action, complete_action, fail_action

    entry = log_action(
        session=session,
        company_id=task.company_id,
        agent_name="f1_collections",
        action_type="send_dunning_whatsapp",
        autonomy_level="A2",
        input_data={"dealer_id": 42, "overdue_days": 15, "amount_inr": 125000},
        output_data={"message_draft": "Dear Dealer ..."},
        rationale="Dealer 42 is 15 days overdue on INR 1.25L. Dunning ladder: tier-2 firm reminder.",
        agent_task_id=task.id,
        entity_type="lead",
        entity_id=42,
    )
    # entry.status == "proposed" — sits in approval queue

    # After human approves and message is sent:
    complete_action(session, entry.id, executed_result={"whatsapp_msg_id": "wamid.xyz"})
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlmodel import Session

from models.models import ActionLedger, AgentKpiEvent, utc_now

logger = logging.getLogger(__name__)


def log_action(
    session: Session,
    company_id: int,
    agent_name: str,
    action_type: str,
    autonomy_level: str,
    input_data: dict,
    output_data: dict,
    rationale: str,
    *,
    agent_task_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    status: str = "proposed",
) -> ActionLedger:
    """Create and persist one ActionLedger row.

    For A1/A2 agents: call with status="proposed" — the row sits pending approval.
    For A3 agents:    call with status="auto_executed" — no approval required.

    Never raises — logs the exception and returns a minimal entry so the caller
    can continue even if the ledger write fails (observability, not blocking).
    """
    entry = ActionLedger(
        company_id=company_id,
        agent_name=agent_name,
        action_type=action_type,
        autonomy_level=autonomy_level,
        input_snapshot=input_data,
        output_snapshot=output_data,
        rationale=rationale,
        status=status,
        agent_task_id=agent_task_id,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    try:
        session.add(entry)
        session.flush()  # get the id without committing the outer transaction
    except Exception:
        logger.exception(
            "[action_ledger] failed to write ledger row — agent=%s action=%s",
            agent_name, action_type,
        )
    return entry


def approve_action(
    session: Session,
    ledger_id: int,
    reviewer_user_id: int,
    note: Optional[str] = None,
) -> Optional[ActionLedger]:
    """Mark a proposed ledger entry as approved. Called by the approval console."""
    entry = session.get(ActionLedger, ledger_id)
    if not entry:
        logger.warning("[action_ledger] approve_action: id=%d not found", ledger_id)
        return None
    entry.status = "approved"
    entry.approved_by_user_id = reviewer_user_id
    entry.approved_at = datetime.now(timezone.utc)
    entry.reviewer_note = note
    session.add(entry)
    return entry


def reject_action(
    session: Session,
    ledger_id: int,
    reviewer_user_id: int,
    note: Optional[str] = None,
) -> Optional[ActionLedger]:
    """Mark a proposed ledger entry as rejected."""
    entry = session.get(ActionLedger, ledger_id)
    if not entry:
        logger.warning("[action_ledger] reject_action: id=%d not found", ledger_id)
        return None
    entry.status = "rejected"
    entry.approved_by_user_id = reviewer_user_id
    entry.approved_at = datetime.now(timezone.utc)
    entry.reviewer_note = note
    session.add(entry)
    return entry


def complete_action(
    session: Session,
    ledger_id: int,
    executed_result: Optional[dict] = None,
) -> Optional[ActionLedger]:
    """Mark an approved entry as executed. Called after the real-world action succeeds."""
    entry = session.get(ActionLedger, ledger_id)
    if not entry:
        logger.warning("[action_ledger] complete_action: id=%d not found", ledger_id)
        return None
    entry.status = "executed"
    entry.executed_at = datetime.now(timezone.utc)
    if executed_result:
        entry.output_snapshot = {**entry.output_snapshot, "execution_result": executed_result}
    session.add(entry)
    return entry


def fail_action(
    session: Session,
    ledger_id: int,
    error: str,
) -> Optional[ActionLedger]:
    """Mark an entry as failed after an execution error."""
    entry = session.get(ActionLedger, ledger_id)
    if not entry:
        logger.warning("[action_ledger] fail_action: id=%d not found", ledger_id)
        return None
    entry.status = "failed"
    entry.executed_at = datetime.now(timezone.utc)
    entry.error = error[:2000]  # guard against huge stack traces
    session.add(entry)
    return entry


def record_kpi(
    session: Session,
    company_id: int,
    agent_name: str,
    metric_name: str,
    metric_value: Any,
    *,
    period_date: Optional[datetime] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    action_ledger_id: Optional[int] = None,
    metadata: Optional[dict] = None,
) -> AgentKpiEvent:
    """Write one KPI data point.  Call alongside log_action for measurable outcomes.

    Example:
        record_kpi(session, task.company_id, "f1_collections",
                   "dunning_messages_sent", 1,
                   entity_type="lead", entity_id=dealer_id)
    """
    event = AgentKpiEvent(
        company_id=company_id,
        agent_name=agent_name,
        metric_name=metric_name,
        metric_value=str(metric_value),
        period_date=period_date or datetime.now(timezone.utc),
        entity_type=entity_type,
        entity_id=entity_id,
        action_ledger_id=action_ledger_id,
        metadata_json=metadata,
    )
    try:
        session.add(event)
        session.flush()
    except Exception:
        logger.exception(
            "[action_ledger] failed to write kpi event — agent=%s metric=%s",
            agent_name, metric_name,
        )
    return event

"""
Approver Routing Service — rule-based approver assignment and SLA escalation.

resolve_approvers() is called by the policy engine and by the approval creation
flow to determine which users must sign off on a given action.

check_escalations() is called by the automation worker on each cycle to detect
pending approvals that have breached their SLA and escalate them automatically.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from models.models import AgentApproval, ApproverRoute, EscalationRule, utc_now

logger = logging.getLogger(__name__)


def _matches(condition: dict, action_type: str, context: dict) -> bool:
    """
    Evaluate a single ApproverRoute condition dict against an action_type and context.

    All specified keys are AND-combined; missing keys are treated as a wildcard (pass).
    """
    if "action_type" in condition and condition["action_type"] != action_type:
        return False
    if "amount_gt" in condition and context.get("amount", 0) <= condition["amount_gt"]:
        return False
    if "amount_lte" in condition and context.get("amount", 0) > condition["amount_lte"]:
        return False
    if "discount_gt" in condition and context.get("discount_percent", 0) <= condition["discount_gt"]:
        return False
    if "risk_level" in condition and context.get("risk_level") != condition["risk_level"]:
        return False
    if "customer_tier" in condition and context.get("customer_tier") != condition["customer_tier"]:
        return False
    return True


def resolve_approvers(
    session: Session,
    company_id: int,
    action_type: str,
    context: dict,
) -> list[int]:
    """
    Evaluate active ApproverRoutes ordered by priority (ascending).

    Returns the approver_user_ids from the first matching route.
    Returns [] if no route matches.

    Parameters
    ----------
    session     : Active SQLModel session.
    company_id  : Tenant ID.
    action_type : Short action identifier (e.g. "send_invoice", "create_order").
    context     : Same context dict as used by the policy engine (amount,
                  discount_percent, customer_tier, risk_level, …).
    """
    context = context or {}
    routes = session.exec(
        select(ApproverRoute).where(
            ApproverRoute.company_id == company_id,
            ApproverRoute.is_active == True,
        ).order_by(ApproverRoute.priority.asc())
    ).all()

    for route in routes:
        condition: dict = route.condition_json or {}
        if _matches(condition, action_type, context):
            approvers: list = route.approver_user_ids or []
            result = [int(uid) for uid in approvers]
            logger.debug(
                "[ApproverRouting] Matched route '%s' (id=%s) for action=%s → approvers=%s",
                route.name, route.id, action_type, result,
            )
            return result

    logger.debug(
        "[ApproverRouting] No route matched for company=%s action=%s",
        company_id, action_type,
    )
    return []


def check_escalations(session: Session, company_id: int) -> int:
    """
    Escalate pending approvals that have breached their SLA.

    For each pending AgentApproval, checks whether any active EscalationRule
    covers the approval's action_type and whether trigger_after_hours has elapsed
    since the approval was created. If so, the escalation target user IDs are
    appended to the approval's reviewer pool via reviewer_note.

    Returns the count of approvals that were escalated in this cycle.

    Called by the automation worker once per cycle.
    """
    now = utc_now()

    pending_approvals = session.exec(
        select(AgentApproval).where(
            AgentApproval.company_id == company_id,
            AgentApproval.status == "pending",
        )
    ).all()

    if not pending_approvals:
        return 0

    active_rules = session.exec(
        select(EscalationRule).where(
            EscalationRule.company_id == company_id,
            EscalationRule.is_active == True,
        )
    ).all()

    if not active_rules:
        return 0

    escalated_count = 0

    for approval in pending_approvals:
        elapsed_hours = (now - approval.created_at).total_seconds() / 3600

        for rule in active_rules:
            # Check if this rule covers the approval's action_type
            action_types: list = rule.action_types or []
            if action_types and approval.action_type not in action_types:
                continue

            # Check if SLA has been breached
            if elapsed_hours < rule.trigger_after_hours:
                continue

            # Already escalated by this rule? Check reviewer_note to avoid duplicates.
            escalation_tag = f"[ESCALATED rule={rule.id}]"
            if approval.reviewer_note and escalation_tag in approval.reviewer_note:
                continue

            # Mark escalation in reviewer_note
            escalate_to: list = rule.escalate_to_user_ids or []
            escalate_to_ids = [int(uid) for uid in escalate_to]
            note_fragment = (
                f"{escalation_tag} After {rule.trigger_after_hours}h SLA breach, "
                f"escalating to user_ids={escalate_to_ids}."
            )
            existing_note = approval.reviewer_note or ""
            approval.reviewer_note = f"{existing_note}\n{note_fragment}".strip()
            approval.updated_at = now
            session.add(approval)

            logger.info(
                "[ApproverRouting] Escalated approval id=%s action=%s to users=%s (rule=%s)",
                approval.id, approval.action_type, escalate_to_ids, rule.id,
            )
            escalated_count += 1
            break  # Apply only the first matching rule per approval per cycle

    if escalated_count:
        session.commit()
        logger.info(
            "[ApproverRouting] Escalated %d approvals for company=%s",
            escalated_count, company_id,
        )

    return escalated_count

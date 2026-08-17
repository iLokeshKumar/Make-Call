"""
Policy Engine — central automation governance layer.

Every automated action that touches money, customers, or high-risk data
runs through evaluate() before execution. The function returns a PolicyDecision
that tells the caller whether to proceed, pause for approval, or block.

Decision priority (first rule that fires wins for needs_approval/blocked):
  1. Discount rules
  2. Invoice send rules
  3. Order/inventory commit rules
  4. Generic high-value rules
  5. Fallback → auto_execute
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from sqlmodel import Session, select

from models.models import ApproverRoute, PolicyDecisionLog, utc_now

logger = logging.getLogger(__name__)


@dataclass
class PolicyDecision:
    decision: Literal["auto_execute", "needs_approval", "blocked"]
    reasons: list[str] = field(default_factory=list)
    risk_score: Decimal = Decimal("0.00")
    required_approvers: list[int] = field(default_factory=list)


def _compute_risk_score(context: dict) -> Decimal:
    """
    Compute a 0-100 risk score from context keys.
    Factors are additive; capped at 100.
    """
    score = 0
    amount: float = context.get("amount", 0) or 0
    discount_percent: float = context.get("discount_percent", 0) or 0
    customer_tier: str = context.get("customer_tier", "") or ""

    if context.get("has_overdue_invoices"):
        score += 20
    if context.get("is_disputed_account"):
        score += 30
    # +10 per 1% discount over 2%
    if discount_percent > 2:
        score += int(discount_percent - 2) * 10
    if customer_tier == "high_risk":
        score += 15
    if amount > 500000:
        score += 25
    if amount > 1000000:
        score += 40   # additive on top of the 500k bump

    score = min(score, 100)
    return Decimal(str(score))


def _resolve_approvers(session: Session, company_id: int, action_type: str, context: dict) -> list[int]:
    """
    Query ApproverRoute table and return approver_user_ids from the first matching
    active route ordered by priority ascending.
    """
    routes = session.exec(
        select(ApproverRoute).where(
            ApproverRoute.company_id == company_id,
            ApproverRoute.is_active == True,
        ).order_by(ApproverRoute.priority.asc())
    ).all()

    for route in routes:
        condition: dict = route.condition_json or {}
        if _route_matches(condition, action_type, context):
            approvers: list = route.approver_user_ids or []
            return [int(uid) for uid in approvers]

    return []


def _route_matches(condition: dict, action_type: str, context: dict) -> bool:
    """Evaluate a single ApproverRoute condition dict against action_type + context."""
    if "action_type" in condition and condition["action_type"] != action_type:
        return False
    amount = context.get("amount", 0) or 0
    if "amount_gt" in condition and amount <= condition["amount_gt"]:
        return False
    if "amount_lte" in condition and amount > condition["amount_lte"]:
        return False
    discount_percent = context.get("discount_percent", 0) or 0
    if "discount_gt" in condition and discount_percent <= condition["discount_gt"]:
        return False
    if "risk_level" in condition and context.get("risk_level") != condition["risk_level"]:
        return False
    if "customer_tier" in condition and context.get("customer_tier") != condition["customer_tier"]:
        return False
    return True


def evaluate(
    session: Session,
    company_id: int,
    action_type: str,
    context: dict,
    actor_agent: str | None = None,
) -> PolicyDecision:
    """
    Evaluate a proposed automated action against company policy rules.

    Parameters
    ----------
    session      : Active SQLModel session.
    company_id   : Tenant ID.
    action_type  : Short identifier, e.g. "send_invoice", "create_order", "apply_discount".
    context      : Dict with optional keys: amount, discount_percent, lead_id, order_id,
                   invoice_id, customer_tier, has_overdue_invoices, is_disputed_account,
                   requires_manual_review.
    actor_agent  : Optional agent identifier for audit trail.

    Returns
    -------
    PolicyDecision with decision, reasons, risk_score, required_approvers.
    """
    context = context or {}
    amount: float = float(context.get("amount", 0) or 0)
    discount_percent: float = float(context.get("discount_percent", 0) or 0)
    customer_tier: str = (context.get("customer_tier") or "").lower()
    has_overdue_invoices: bool = bool(context.get("has_overdue_invoices", False))
    is_disputed_account: bool = bool(context.get("is_disputed_account", False))
    requires_manual_review: bool = bool(context.get("requires_manual_review", False))

    decision: Literal["auto_execute", "needs_approval", "blocked"] = "auto_execute"
    reasons: list[str] = []
    handled = False

    # ── Discount rules ──────────────────────────────────────────────────────
    is_discount_action = "discount" in action_type.lower() or "discount_percent" in context
    if is_discount_action:
        handled = True
        if discount_percent > 7:
            decision = "blocked"
            reasons.append("Discount >7% requires senior approval")
        elif discount_percent > 2:
            decision = "needs_approval"
            reasons.append("Discount >2% requires manager approval")
        # else stays auto_execute

    # ── Invoice send rules ───────────────────────────────────────────────────
    if not handled and action_type == "send_invoice":
        handled = True
        if is_disputed_account:
            decision = "blocked"
            reasons.append("Account has active dispute")
        elif has_overdue_invoices and amount > 100000:
            decision = "needs_approval"
            reasons.append("High-value invoice with overdue history")
        elif requires_manual_review:
            decision = "needs_approval"
            reasons.append("Manual review flagged")
        # else stays auto_execute

    # ── Order commit rules ───────────────────────────────────────────────────
    if not handled and action_type in ("commit_inventory", "create_order"):
        handled = True
        if amount > 1000000:
            decision = "needs_approval"
            reasons.append("Order value exceeds auto-commit threshold")
        elif customer_tier == "high_risk":
            decision = "needs_approval"
            reasons.append("High-risk customer account")
        # else stays auto_execute

    # ── Generic high-value rules ─────────────────────────────────────────────
    if not handled and amount > 500000:
        decision = "needs_approval"
        reasons.append("High-value action requires approval")

    # ── Risk scoring ─────────────────────────────────────────────────────────
    risk_score = _compute_risk_score(context)

    # ── Resolve required approvers ────────────────────────────────────────────
    required_approvers: list[int] = []
    if decision in ("needs_approval", "blocked"):
        try:
            required_approvers = _resolve_approvers(session, company_id, action_type, context)
        except Exception:
            logger.exception("[PolicyEngine] Failed to resolve approvers for company=%s", company_id)

    # ── Persist decision log ──────────────────────────────────────────────────
    # Derive entity hints from context if available
    entity_type = "action"
    entity_id: int | None = None
    if context.get("order_id"):
        entity_type = "order"
        entity_id = int(context["order_id"])
    elif context.get("invoice_id"):
        entity_type = "invoice"
        entity_id = int(context["invoice_id"])
    elif context.get("lead_id"):
        entity_type = "lead"
        entity_id = int(context["lead_id"])

    try:
        log_entry = PolicyDecisionLog(
            company_id=company_id,
            entity_type=entity_type,
            entity_id=entity_id,
            action_type=action_type,
            decision=decision,
            reasons=reasons,
            risk_score=risk_score,
            required_approvers=required_approvers,
            context_json=context,
            actor_agent=actor_agent,
        )
        session.add(log_entry)
        session.commit()
    except Exception:
        logger.exception(
            "[PolicyEngine] Failed to persist PolicyDecisionLog for company=%s action=%s",
            company_id, action_type,
        )
        session.rollback()

    result = PolicyDecision(
        decision=decision,
        reasons=reasons,
        risk_score=risk_score,
        required_approvers=required_approvers,
    )
    logger.info(
        "[PolicyEngine] company=%s action=%s decision=%s risk=%s reasons=%s",
        company_id, action_type, decision, risk_score, reasons,
    )
    return result

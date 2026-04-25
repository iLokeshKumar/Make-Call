"""ISM Rules Engine — data-driven stage/action overrides.

A rule is a DB row (IsmRule) with:
  - when_json: a JSON condition object (see models.IsmRule docstring for the DSL)
  - then_action: a string like "advance_to:negotiation" or "dispatch:send_quote"

`evaluate_rules(session, company_id, lead)` returns the FIRST matching rule
in priority order (lowest priority number = highest precedence), or None if
no rule matches.

Design notes
------------
1. Pure-ish: read-only on the session, no writes. Returns the rule; caller
   decides whether to execute the action. Makes the evaluator trivially
   testable and auditable.
2. Defensive on missing fields: if a condition references a lead attribute
   that's null/missing, the condition fails (rather than the rule firing
   spuriously). Conservative default.
3. No DSL-escape hatches: every operator is an explicit key in when_json.
   No arbitrary Python or SQL evaluation — ops get capability without
   injection surface.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Optional

from sqlmodel import Session, select

from models.models import IsmRule, Lead, LeadRequirement, utc_now

logger = logging.getLogger(__name__)


# Operator implementations — one per when_json key.
# Each returns True if the condition matches, False otherwise. Missing or
# unparseable data returns False (conservative).


def _op_stage(lead: Lead, value: Any) -> bool:
    return str(lead.ism_stage or "") == str(value)


def _op_stages(lead: Lead, value: Any) -> bool:
    if not isinstance(value, (list, tuple)):
        return False
    return str(lead.ism_stage or "") in {str(v) for v in value}


def _op_has_email(lead: Lead, value: Any) -> bool:
    actual = bool(lead.email)
    return actual == bool(value)


def _op_has_phone(lead: Lead, value: Any) -> bool:
    actual = bool(lead.normalized_phone)
    return actual == bool(value)


def _op_lead_score_min(lead: Lead, value: Any) -> bool:
    if lead.lead_score is None:
        return False
    try:
        return float(lead.lead_score) >= float(value)
    except (TypeError, ValueError):
        return False


def _op_lead_score_max(lead: Lead, value: Any) -> bool:
    if lead.lead_score is None:
        return False
    try:
        return float(lead.lead_score) <= float(value)
    except (TypeError, ValueError):
        return False


def _op_days_since_contact_min(lead: Lead, value: Any) -> bool:
    """lead.last_outreach_at was at LEAST N days ago (or never happened)."""
    try:
        days = float(value)
    except (TypeError, ValueError):
        return False
    # Never contacted → infinity → any "at least N" matches
    if lead.last_outreach_at is None:
        return True
    # SQLite returns naive datetime; pair with naive utc_now for comparison
    last = lead.last_outreach_at
    if last.tzinfo is None:
        now = utc_now().replace(tzinfo=None)
    else:
        now = utc_now()
    return (now - last) >= timedelta(days=days)


def _op_days_since_contact_max(lead: Lead, value: Any) -> bool:
    """lead.last_outreach_at was at MOST N days ago (must have been contacted)."""
    try:
        days = float(value)
    except (TypeError, ValueError):
        return False
    if lead.last_outreach_at is None:
        return False   # never contacted → definitely > max
    last = lead.last_outreach_at
    if last.tzinfo is None:
        now = utc_now().replace(tzinfo=None)
    else:
        now = utc_now()
    return (now - last) <= timedelta(days=days)


# Operators that need the LeadRequirement — looked up lazily.


def _get_requirement(session: Session, company_id: int, lead_id: int) -> Optional[LeadRequirement]:
    return session.exec(
        select(LeadRequirement)
        .where(
            LeadRequirement.company_id == company_id,
            LeadRequirement.lead_id == lead_id,
        )
        .order_by(LeadRequirement.created_at.desc(), LeadRequirement.id.desc())
    ).first()


def _parse_budget_usd(text: Optional[str]) -> Optional[float]:
    """Parse a budget_range free-text string to USD estimate (or None).

    Mirrors the ism_orchestrator logic — kept here separately so the rules
    engine has no circular dependency on ism_orchestrator. Tests lock both
    versions to the same behavior via shared fixtures.
    """
    if not text:
        return None
    import re
    t = text.lower().strip()
    max_native = 0.0
    suffixes = {
        "k": 1_000, "thousand": 1_000,
        "m": 1_000_000, "mil": 1_000_000, "million": 1_000_000,
        "l": 100_000, "lac": 100_000, "lakh": 100_000,
        "cr": 10_000_000, "crore": 10_000_000,
    }
    for m in re.finditer(r"(\d+(?:[.,]\d+)?)\s*([a-z]*)", t):
        try:
            num = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        mult = suffixes.get(m.group(2), 1.0)
        max_native = max(max_native, num * mult)
    if max_native == 0:
        return None
    is_inr = any(marker in t for marker in ("₹", "inr", "rs ", "rupee", "lakh", "lac", "crore"))
    return max_native / 80.0 if is_inr else max_native


def _op_budget_usd_min(requirement: Optional[LeadRequirement], value: Any) -> bool:
    if requirement is None:
        return False
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        return False
    # structured_data wins
    sd = getattr(requirement, "structured_data", None) or {}
    try:
        explicit = sd.get("budget_max_usd")
        if explicit is not None:
            return float(explicit) >= threshold
    except (TypeError, ValueError):
        pass
    parsed = _parse_budget_usd(requirement.budget_range)
    return parsed is not None and parsed >= threshold


def _op_budget_usd_max(requirement: Optional[LeadRequirement], value: Any) -> bool:
    if requirement is None:
        return False
    try:
        threshold = float(value)
    except (TypeError, ValueError):
        return False
    sd = getattr(requirement, "structured_data", None) or {}
    try:
        explicit = sd.get("budget_max_usd")
        if explicit is not None:
            return float(explicit) <= threshold
    except (TypeError, ValueError):
        pass
    parsed = _parse_budget_usd(requirement.budget_range)
    return parsed is not None and parsed <= threshold


_URGENT_TIMELINE_KEYWORDS = frozenset({
    "immediate", "urgent", "asap", "rush", "rushing",
    "today", "tomorrow", "tonight", "right now",
    "this week", "next 7 days", "next week",
})


def _op_urgency(requirement: Optional[LeadRequirement], value: Any) -> bool:
    if requirement is None:
        return False
    expected = str(value or "").lower().strip()
    sd = getattr(requirement, "structured_data", None) or {}
    actual_urgency = str(sd.get("urgency") or "").lower()
    if actual_urgency in {"urgent", "immediate", "rush"}:
        actual = "urgent"
    else:
        text = (requirement.timeline or "").lower()
        actual = "urgent" if any(kw in text for kw in _URGENT_TIMELINE_KEYWORDS) else "routine"
    return actual == expected


# Evaluation


def _evaluate_when(
    when_json: dict,
    *,
    lead: Lead,
    requirement: Optional[LeadRequirement],
) -> bool:
    """Evaluate every key in when_json — ALL must match for the rule to fire."""
    if not when_json:
        # An empty condition matches everything — explicit opt-in behavior
        # (ops can build a catch-all rule with priority=999 as a safety net).
        return True

    for key, value in when_json.items():
        if key == "stage":
            if not _op_stage(lead, value):
                return False
        elif key == "stages":
            if not _op_stages(lead, value):
                return False
        elif key == "has_email":
            if not _op_has_email(lead, value):
                return False
        elif key == "has_phone":
            if not _op_has_phone(lead, value):
                return False
        elif key == "lead_score_min":
            if not _op_lead_score_min(lead, value):
                return False
        elif key == "lead_score_max":
            if not _op_lead_score_max(lead, value):
                return False
        elif key == "days_since_contact_min":
            if not _op_days_since_contact_min(lead, value):
                return False
        elif key == "days_since_contact_max":
            if not _op_days_since_contact_max(lead, value):
                return False
        elif key == "budget_usd_min":
            if not _op_budget_usd_min(requirement, value):
                return False
        elif key == "budget_usd_max":
            if not _op_budget_usd_max(requirement, value):
                return False
        elif key == "urgency":
            if not _op_urgency(requirement, value):
                return False
        else:
            # Unknown operator — rule can't safely fire. Log and fail closed.
            logger.warning("[ism_rules] unknown when_json operator: %r — rule does not match", key)
            return False
    return True


def evaluate_rules(
    session: Session,
    company_id: int,
    lead: Lead,
) -> Optional[IsmRule]:
    """Return the first matching IsmRule in priority order, or None.

    Priority semantics: lower number = higher precedence. Rules with the
    same priority are ordered by id (stable). Inactive rules are skipped.
    """
    rules = session.exec(
        select(IsmRule)
        .where(IsmRule.company_id == company_id, IsmRule.is_active == True)  # noqa: E712
        .order_by(IsmRule.priority.asc(), IsmRule.id.asc())
    ).all()

    if not rules:
        return None

    requirement: Optional[LeadRequirement] = None
    needs_requirement = any(
        any(k in (r.when_json or {}) for k in ("budget_usd_min", "budget_usd_max", "urgency"))
        for r in rules
    )
    if needs_requirement:
        requirement = _get_requirement(session, company_id, lead.id)

    for rule in rules:
        if _evaluate_when(rule.when_json or {}, lead=lead, requirement=requirement):
            logger.debug(
                "[ism_rules] matched rule id=%s name=%s for lead=%s",
                rule.id, rule.name, lead.id,
            )
            return rule
    return None


# Action parsing — pure string → structured tuple, no side effects

def parse_action(action: str) -> tuple[str, Optional[str]]:
    """Split 'verb:argument' into (verb, argument) or (verb, None).

    Verbs: advance_to, dispatch, handoff_to_human, skip.
    """
    if not action:
        return ("skip", None)
    if ":" in action:
        verb, _, arg = action.partition(":")
        return (verb.strip(), arg.strip() or None)
    return (action.strip(), None)

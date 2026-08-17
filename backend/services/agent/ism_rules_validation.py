"""Pure validation helpers for ISM rules routes.

Split from `routes.ism_rules` so tests can import validation logic without
pulling in auth (and its pyotp dependency). Same pattern as `csrf.py` for
the CSRF invariants — pure stdlib-only module.
"""
from __future__ import annotations

from fastapi import HTTPException

# Must stay in sync with agents.ism_rules_engine and ism_orchestrator.
# If the DSL evolves, update both places (tests catch drift).

_ALLOWED_WHEN_KEYS: frozenset[str] = frozenset({
    "stage", "stages",
    "has_email", "has_phone",
    "lead_score_min", "lead_score_max",
    "days_since_contact_min", "days_since_contact_max",
    "budget_usd_min", "budget_usd_max",
    "urgency",
})

_ALLOWED_ACTION_VERBS: frozenset[str] = frozenset({
    "advance_to",
    "dispatch",
    "handoff_to_human",
    "skip",
})

_VALID_DISPATCH_ARGS: frozenset[str] = frozenset({
    "call", "whatsapp", "email", "send_email", "send_whatsapp", "send_quote",
})

_VALID_STAGES: frozenset[str] = frozenset({
    "new", "contacted", "engaged", "quote_sent", "negotiation",
    "closed_won", "closed_lost",
})


def validate_when_json(when_json: dict) -> None:
    """Reject unknown operators at write time. Raises HTTPException(400)."""
    if not isinstance(when_json, dict):
        raise HTTPException(status_code=400, detail="when_json must be a JSON object")
    for key in when_json:
        if key not in _ALLOWED_WHEN_KEYS:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown when_json operator: {key!r}. Valid: {sorted(_ALLOWED_WHEN_KEYS)}",
            )


def validate_then_action(then_action: str) -> None:
    """Reject malformed actions at write time. Raises HTTPException(400)."""
    if not then_action or not isinstance(then_action, str):
        raise HTTPException(status_code=400, detail="then_action is required (string)")
    verb, _, arg = then_action.partition(":")
    verb = verb.strip()
    if verb not in _ALLOWED_ACTION_VERBS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action verb: {verb!r}. Valid: {sorted(_ALLOWED_ACTION_VERBS)}",
        )
    arg = arg.strip()
    if verb == "advance_to":
        if arg not in _VALID_STAGES:
            raise HTTPException(
                status_code=400,
                detail=f"advance_to requires a valid stage. Got {arg!r}, valid: {sorted(_VALID_STAGES)}",
            )
    if verb == "dispatch":
        if arg not in _VALID_DISPATCH_ARGS:
            raise HTTPException(
                status_code=400,
                detail=f"dispatch requires one of {sorted(_VALID_DISPATCH_ARGS)}. Got {arg!r}",
            )

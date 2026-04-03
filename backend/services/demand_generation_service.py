from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlmodel import Session, select

from credentials_service import get_company_setting_value
from models.models import CallTask, Lead, utc_now
from services.outbound_call_service import create_call_task


def _score_to_decimal(value: float) -> Decimal:
    return Decimal(str(round(value, 2))).quantize(Decimal("0.01"))


def compute_icp_score(lead: Lead) -> dict[str, Any]:
    score = 0.0
    reasons: list[str] = []

    if lead.email:
        score += 20
        reasons.append("lead_has_email")
    if lead.website:
        score += 15
        reasons.append("lead_has_website")
    if lead.industry and lead.industry.lower() in {
        "tech",
        "saas",
        "manufacturing",
        "electronics",
        "healthcare",
        "finance",
        "retail",
        "distribution",
    }:
        score += 25
        reasons.append("target_industry_match")
    if lead.job_title and any(keyword in lead.job_title.lower() for keyword in ["manager", "head", "director", "owner", "founder"]):
        score += 15
        reasons.append("decision_maker_seniority")
    if lead.source and lead.source.lower() in {"apollo api", "apollo", "voice_agent"}:
        score += 10
        reasons.append("high_intent_source")
    if lead.enrichment_status and lead.enrichment_status.lower() != "not_enriched":
        score += 15
        reasons.append("already_enriched")

    priority = "low"
    if score >= 70:
        priority = "high"
    elif score >= 40:
        priority = "medium"

    return {
        "score": _score_to_decimal(min(score, 100)),
        "reasons": reasons,
        "priority": priority,
    }


def score_lead(session: Session, company_id: int, lead_id: int) -> dict[str, Any]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return {"error": "Lead not found"}

    scoring = compute_icp_score(lead)
    lead.lead_score = scoring["score"]
    lead.lead_score_reasons_json = {"reasons": scoring["reasons"], "priority": scoring["priority"]}
    lead.updated_at = utc_now()
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return {
        "lead_id": lead.id,
        "score": str(lead.lead_score) if lead.lead_score is not None else None,
        "priority": scoring["priority"],
        "reasons": scoring["reasons"],
    }


def enrich_lead_if_needed(session: Session, company_id: int, actor_user_id: int, lead_id: int) -> dict[str, Any]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return {"error": "Lead not found"}

    updated = False
    if lead.email and "@" in lead.email and not lead.website:
        domain = lead.email.split("@")[-1].strip().lower()
        if domain:
            lead.website = f"https://{domain}"
            updated = True
    if lead.email and lead.enrichment_status == "not_enriched":
        lead.enrichment_status = "basic_enriched"
        updated = True
    if updated:
        lead.last_enriched_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        session.refresh(lead)

    return {
        "lead_id": lead.id,
        "enrichment_status": lead.enrichment_status,
        "website": lead.website,
        "updated": updated,
    }


def choose_outreach_strategy(session: Session, company_id: int, lead_id: int, score_payload: dict[str, Any]) -> dict[str, Any]:
    score_text = score_payload.get("score")
    score = Decimal(score_text) if score_text is not None else Decimal("0")
    if score >= Decimal("70"):
        return {
            "strategy": "immediate_call_task",
            "schedule_call": True,
            "delay_minutes": 5,
        }
    if score >= Decimal("40"):
        return {
            "strategy": "near_term_call_task",
            "schedule_call": True,
            "delay_minutes": 60,
        }
    return {
        "strategy": "nurture_only",
        "schedule_call": False,
        "delay_minutes": None,
    }


def _auto_trigger_enabled(session: Session, company_id: int) -> bool:
    value = get_company_setting_value(session, company_id, "AUTO_TRIGGER_NEW_LEADS")
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def trigger_new_lead_outreach(session: Session, company_id: int, actor_user_id: int, lead_id: int) -> dict[str, Any]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return {"error": "Lead not found"}

    enrichment_result = enrich_lead_if_needed(session, company_id, actor_user_id, lead_id)
    scoring = score_lead(session, company_id, lead_id)
    if scoring.get("error"):
        return scoring

    strategy = choose_outreach_strategy(session, company_id, lead_id, scoring)
    result: dict[str, Any] = {
        "lead_id": lead_id,
        "enrichment": enrichment_result,
        "scoring": scoring,
        "strategy": strategy,
    }

    if not _auto_trigger_enabled(session, company_id):
        result["auto_triggered"] = False
        result["reason"] = "AUTO_TRIGGER_NEW_LEADS disabled"
        return result

    if strategy["schedule_call"]:
        from datetime import timedelta

        scheduled_at = utc_now() + timedelta(minutes=int(strategy["delay_minutes"]))
        task = create_call_task(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            assigned_user_id=lead.owner_user_id or actor_user_id,
            scheduled_at=scheduled_at,
            notes=f"Auto-created from demand generation service ({strategy['strategy']})",
            dialer_source="demand_generation",
        )
        lead.next_action = "follow_up_call"
        lead.next_action_due_at = scheduled_at
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        result["auto_triggered"] = True
        result["call_task_id"] = task.id
        return result

    result["auto_triggered"] = False
    result["reason"] = "Lead scored below auto-call threshold"
    return result


def process_recent_unscored_leads(
    session: Session,
    company_id: int,
    actor_user_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    leads = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.lead_score.is_(None),
        ).order_by(Lead.created_at.desc()).limit(limit)
    ).all()
    results: list[dict[str, Any]] = []
    for lead in leads:
        results.append(trigger_new_lead_outreach(session, company_id, actor_user_id, lead.id))
    return results


def get_scheduled_call_task_for_lead(session: Session, company_id: int, lead_id: int) -> CallTask | None:
    return session.exec(
        select(CallTask).where(
            CallTask.company_id == company_id,
            CallTask.lead_id == lead_id,
            CallTask.dialer_source == "demand_generation",
        ).order_by(CallTask.created_at.desc())
    ).first()

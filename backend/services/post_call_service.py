import json
import logging

from sqlmodel import Session, select

from models.models import Interaction, LeadRequirementUpsert, User
from services.requirement_service import upsert_lead_requirements

logger = logging.getLogger(__name__)


POST_CALL_EXTRACTION_PROMPT = """
You are extracting structured B2B sales intelligence from a completed sales call.

Return ONLY valid JSON with these keys:
{
"use_case": string or null,
"budget_range": string or null,
"timeline": string or null,
"decision_maker": string or null,
"competitors": string or null,
"pain_points": string or null,
"required_products": string or null,
"qualification_status": string or null,
"next_action": string or null,
"industry": string or null,
"website": string or null,
"city": string or null,
"state": string or null,
"country": string or null
}

Rules:
- Use null when unknown.
- Keep values short and business-usable.
- qualification_status should be one of:
"unqualified", "qualified", "proposal", "follow_up", "not_interested"
- next_action should be one of:
"send_quote", "send_brochure", "schedule_demo", "follow_up_call", "follow_up_email", "close_lost", "none"
- Do not include markdown.
- Do not include explanation text.
"""


def _safe_parse_json(text: str) -> dict | None:
    try:
        return json.loads(text)
    except Exception:
        return None


async def extract_and_save_requirements(
    session: Session,
    llm_service,
    company_id: int,
    actor_user_id: int,
    interaction_id: int,
    lead_id: int,
    transcript: str,
):
    if not transcript or not transcript.strip():
        logger.info("No transcript available for post-call extraction")
        return None

    try:
        prompt = (
            f"{POST_CALL_EXTRACTION_PROMPT}\n\n"
            f"CALL TRANSCRIPT:\n{transcript}\n"
        )

        # Assumes your llm service has a simple generation method or equivalent
        result_text = await llm_service.generate(prompt)
        structured = _safe_parse_json(result_text)

        if not structured:
            logger.warning("Post-call extraction did not return valid JSON")
            return None

        payload = LeadRequirementUpsert(
            lead_id=lead_id,
            interaction_id=interaction_id,
            use_case=structured.get("use_case"),
            budget_range=structured.get("budget_range"),
            timeline=structured.get("timeline"),
            decision_maker=structured.get("decision_maker"),
            competitors=structured.get("competitors"),
            pain_points=structured.get("pain_points"),
            required_products=structured.get("required_products"),
            notes="Auto-extracted from post-call transcript",
            structured_data=structured,
        )

        saved = upsert_lead_requirements(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            data=payload,
        )
        return saved

    except Exception as e:
        logger.warning(f"Post-call extraction failed: {e}")
        return None
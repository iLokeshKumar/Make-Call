import json
import logging

from sqlmodel import Session, select

from models.models import Interaction, LeadRequirementUpsert, User
from services.requirement_service import upsert_lead_requirements
from services.objection_service import extract_and_save_objections

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
"country": string or null,
"verbal_rating": integer or null
}

Rules:
- Use null when unknown.
- Keep values short and business-usable.
- qualification_status should be one of:
"unqualified", "qualified", "proposal", "follow_up", "not_interested"
- next_action should be one of:
"send_quote", "send_brochure", "schedule_demo", "follow_up_call", "follow_up_email", "close_lost", "none"
- verbal_rating: if the customer gave a 1-5 rating during the call (e.g. "I'd say a 4"), extract the integer. Otherwise null.
- Do not include markdown.
- Do not include explanation text.
"""


def _safe_parse_json(text: str) -> dict | None:
    if not text:
        return None
    # Try raw parse first
    try:
        return json.loads(text)
    except Exception:
        pass

    import re
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass
    # Last resort: find first { ... } block
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
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

        llm_service.add_user_message(prompt)
        result_text = ""
        async for chunk in llm_service.stream():
            if chunk.get("type") == "finished":
                result_text = chunk.get("full_reply", result_text)
                break
            elif chunk.get("type") == "token":
                result_text += chunk.get("content", "")
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

        # Save verbal rating as internal feedback if the customer gave one on the call
        verbal_rating = structured.get("verbal_rating")
        try:
            verbal_rating = int(verbal_rating) if verbal_rating is not None else None
        except (ValueError, TypeError):
            verbal_rating = None
        if verbal_rating and 1 <= verbal_rating <= 5:
            try:
                from models.models import Feedback, utc_now
                fb = Feedback(
                    company_id=company_id,
                    lead_id=lead_id,
                    interaction_id=interaction_id,
                    submitted_by_user_id=actor_user_id,
                    feedback_type="csat",
                    source="customer",
                    rating=verbal_rating,
                    comment="Verbal rating given on call",
                    status="submitted",
                    responded_at=utc_now(),
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
                session.add(fb)
                session.commit()
                logger.info("[PostCall] Verbal rating=%s saved as feedback for lead %s", verbal_rating, lead_id)
            except Exception as fb_exc:
                logger.warning("[PostCall] Failed to save verbal feedback: %s", fb_exc)

        # Auto-generate and send quote if AI detected "send_quote" intent
        if structured.get("next_action") == "send_quote":
            try:
                from quote.voice_quote_service import auto_generate_and_send_quote
                vq_result = await auto_generate_and_send_quote(
                    session=session,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    lead_id=lead_id,
                    interaction_id=interaction_id,
                    required_products_text=structured.get("required_products"),
                )
                logger.info("[PostCall] Voice quote sent for lead %s: %s", lead_id, vq_result)
            except Exception as vq_exc:
                logger.warning("[PostCall] Voice quote dispatch failed: %s", vq_exc)

        # Fire-and-forget objection extraction using the same LLM service
        # (the LLM message history is already reset by the new prompt above,
        # so we re-instantiate a lightweight version via the same instance)
        try:
            from ai.llm import get_llm_service
            objection_llm = get_llm_service(
                llm_service.provider.lower() if hasattr(llm_service, "provider") else "mistral",
                "You extract sales objections from transcripts.",
                api_key=getattr(llm_service, "api_key", None),
                model=getattr(llm_service, "model", None),
            )
            await extract_and_save_objections(
                session=session,
                llm_service=objection_llm,
                company_id=company_id,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                transcript=transcript,
            )
        except Exception as obj_exc:
            logger.warning("Objection extraction failed: %s", obj_exc)

        # AI Sales Coach — score the AI's performance and optionally auto-tune the system prompt
        try:
            from ai.llm import get_llm_service
            from call.call_coach_service import score_call_and_coach
            coach_llm = get_llm_service(
                llm_service.provider.lower() if hasattr(llm_service, "provider") else "mistral",
                "You are an expert B2B sales coach.",
                api_key=getattr(llm_service, "api_key", None),
                model=getattr(llm_service, "model", None),
            )
            await score_call_and_coach(
                session=session,
                llm_service=coach_llm,
                company_id=company_id,
                actor_user_id=actor_user_id,
                interaction_id=interaction_id,
                lead_id=lead_id,
                transcript=transcript,
            )
        except Exception as coach_exc:
            logger.warning("Coach scoring failed: %s", coach_exc)

        # Personalized follow-up email via EmailWriter for nurture actions
        nurture_actions = {"follow_up_email", "send_brochure", "schedule_demo", "follow_up_call"}
        if structured.get("next_action") in nurture_actions:
            try:
                from agents.post_call_nurture import EmailWriter
                lead_obj = session.get(__import__("models.models", fromlist=["Lead"]).Lead, lead_id)
                if lead_obj and lead_obj.email:
                    raw_pain = structured.get("pain_points") or ""
                    pain_list = [p.strip() for p in raw_pain.split(",") if p.strip()] if raw_pain else []
                    raw_use = structured.get("use_case") or ""
                    questions_list = [raw_use] if raw_use else []
                    EmailWriter.send_personalized_followup(
                        session=session,
                        company_id=company_id,
                        actor_user_id=actor_user_id,
                        lead_id=lead_id,
                        lead_name=lead_obj.name or "there",
                        lead_email=lead_obj.email,
                        company=lead_obj.company_name or "",
                        pain_points=pain_list,
                        questions=questions_list,
                        icp_score=float(lead_obj.lead_score or 0.5),
                        suggested_action=structured.get("next_action"),
                    )
                    logger.info("[PostCall] Follow-up email sent to lead %s", lead_id)
            except Exception as ew_exc:
                logger.warning("[PostCall] EmailWriter dispatch failed: %s", ew_exc)

        # Post-call competitor mention extraction (LLM, more accurate than real-time keywords)
        try:
            from ai.llm import get_llm_service
            from services.competitor_service import extract_and_save_competitor_mentions
            comp_llm = get_llm_service(
                llm_service.provider.lower() if hasattr(llm_service, "provider") else "mistral",
                "You extract competitor mentions from sales call transcripts.",
                api_key=getattr(llm_service, "api_key", None),
                model=getattr(llm_service, "model", None),
            )
            await extract_and_save_competitor_mentions(
                session=session,
                llm_service=comp_llm,
                company_id=company_id,
                lead_id=lead_id,
                interaction_id=interaction_id,
                transcript=transcript,
            )
        except Exception as comp_exc:
            logger.warning("Competitor extraction failed: %s", comp_exc)

        # CSAT feedback email — send after any engaged/positive call
        try:
            from feedback.auto_csat_service import maybe_send_auto_csat, POSITIVE_OUTCOMES
            qual = structured.get("qualification_status") or ""
            # Map extraction qualification_status → normalized_outcome used by CSAT gate
            csat_outcome = (
                "answered_interested" if qual in ("qualified", "proposal")
                else "answered_callback_requested" if qual == "follow_up"
                else ""
            )
            maybe_send_auto_csat(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead_id,
                interaction_id=interaction_id,
                trigger="call",
                normalized_outcome=csat_outcome,
            )
        except Exception as csat_exc:
            logger.warning("[PostCall] CSAT dispatch failed: %s", csat_exc)

        # Orchestrator post-call workflow: save summary → ISM advance → follow-up
        try:
            from agents.orchestrator import run_post_call
            import asyncio
            from models.models import Lead as _Lead

            lead_obj = session.get(_Lead, lead_id)

            # Map LLM-extracted fields → orchestrator inputs
            raw_pain = structured.get("pain_points") or ""
            pain_list = [p.strip() for p in raw_pain.split(",") if p.strip()] if raw_pain else []
            raw_use = structured.get("use_case") or ""
            q_list = [raw_use] if raw_use else []

            qual = structured.get("qualification_status") or "neutral"
            # Normalise qualification_status → call_outcome expected by agents
            _OUTCOME_MAP = {
                "qualified":      "positive",
                "proposal":       "positive",
                "follow_up":      "neutral",
                "unqualified":    "not_qualified",
                "not_interested": "not_qualified",
            }
            call_outcome = _OUTCOME_MAP.get(qual, "neutral")
            sentiment = "positive" if call_outcome == "positive" else "neutral"

            asyncio.create_task(
                run_post_call(
                    lead_id=lead_id,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    lead_name=(lead_obj.name if lead_obj else "") or "",
                    lead_email=(lead_obj.email if lead_obj else "") or "",
                    call_transcript=transcript,
                    call_duration=0,
                    call_outcome=call_outcome,
                    sentiment=sentiment,
                    icp_score=float(lead_obj.lead_score or 0.5) if lead_obj else 0.5,
                    pain_points=pain_list,
                    questions_asked=q_list,
                    bant_answers={
                        "budget":    structured.get("budget_range"),
                        "authority": structured.get("decision_maker"),
                        "need":      structured.get("use_case"),
                        "timeline":  structured.get("timeline"),
                    },
                )
            )
            logger.info("[PostCall] Orchestrator workflow queued for lead %s (outcome=%s)", lead_id, call_outcome)
        except Exception as lg_exc:
            logger.warning("[PostCall] Orchestrator dispatch failed: %s", lg_exc)

        return saved

    except Exception as e:
        logger.warning(f"Post-call extraction failed: {e}")
        return None
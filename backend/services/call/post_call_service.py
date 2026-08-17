import asyncio
import json
import logging
import re

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
"verbal_rating": integer or null,
"verbal_comment": string or null
}

Rules:
- Use null when unknown.
- Keep values short and business-usable.
- qualification_status should be one of:
"unqualified", "qualified", "proposal", "follow_up", "not_interested"
- next_action should be one of:
"send_quote", "send_brochure", "schedule_demo", "follow_up_call", "follow_up_email", "close_lost", "none"
- verbal_rating: if the customer gave an UNAMBIGUOUS 1-5 rating during the call (e.g. "I'd say a 4"), extract the integer. If they gave two numbers ("one or five"), ranges, or refused — return null.  Spoken-form numbers (one, two, three, four, five) count.
- verbal_comment: a SHORT (1-2 sentence) summary of the customer's qualitative feedback AND the reason they gave that rating, drawn from phrases the customer actually used.  Examples:
  * Rating 1 + "you didn't listen, you kept interrupting" → "Didn't listen / kept interrupting."
  * Rating 5 + "everything was clear and the agent was helpful" → "Clear and helpful."
  * Just qualitative ("good service") with no number → "Good service." (rating still null)
  * Ambiguous numeric ("one or five") → "Said one or five — unclear."
  Limit to 200 chars.  ONLY the customer's feedback ABOUT the call / agent — NOT product or business comments.
- Do not include markdown.
- Do not include explanation text.
"""


_WORD_TO_NUM = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "1": 1, "2": 2, "3": 3, "4": 4, "5": 5,
}

# Patterns the customer typically uses when stating a rating in response to
# "on a scale of 1 to 5...".  Order matters: more specific cue words first
# so "rate" trumps a stray digit elsewhere.
_RATING_PATTERNS = [
    # "rate it (as) X", "rated as X", "rating is X"
    re.compile(r"\brat(?:e|ed|ing)\b[^.!?]{0,30}?\b(one|two|three|four|five|[1-5])\b", re.IGNORECASE),
    # "I'd say (a|an) X", "I'll say X", "I would say X"
    re.compile(r"\bi(?:'d|'ll| would| will)?\s+say\b[^.!?]{0,15}?\b(one|two|three|four|five|[1-5])\b", re.IGNORECASE),
    # "give it (a) X", "give X out of 5"
    re.compile(r"\bgive\b[^.!?]{0,15}?\b(one|two|three|four|five|[1-5])\b", re.IGNORECASE),
    # "X out of 5"
    re.compile(r"\b(one|two|three|four|five|[1-5])\s+out\s+of\s+(?:five|5)\b", re.IGNORECASE),
    # bare "five star", "4 stars"
    re.compile(r"\b(one|two|three|four|five|[1-5])\s+star", re.IGNORECASE),
    # just a number/word in a User: line that comes right after the feedback ask
    # (caller scopes to the last 1500 chars so this doesn't false-fire elsewhere)
    re.compile(r"\bUser:\s*(?:it'?s\s+(?:a|an)\s+)?(one|two|three|four|five|[1-5])\b\.?\s*$", re.IGNORECASE | re.MULTILINE),
]


def _regex_extract_verbal_rating(transcript: str | None) -> int | None:
    """Best-effort regex pull of a 1-5 rating from the call transcript tail.

    Returns the LAST match found, since customers sometimes self-correct
    ("one... or maybe a five — let's say five").  Scans only the last 1500
    characters: the SLO #2 question always sits near the end of the call.
    """
    if not transcript:
        return None
    tail = transcript[-1500:]
    last_match: int | None = None
    for pattern in _RATING_PATTERNS:
        for m in pattern.finditer(tail):
            token = m.group(1).lower()
            value = _WORD_TO_NUM.get(token)
            if value and 1 <= value <= 5:
                last_match = value
    return last_match


# Cue words customers use when explaining a rating. Used by the regex comment-extraction fallback.
_REASON_CUES = re.compile(
    r"\b(because|since|didn'?t|wasn'?t|too|kept|never|always|you (?:didn'?t|did not)|"
    r"you (?:were|are)|terrible|awful|bad|poor|frustrat|annoying|interrupt|listen|"
    r"clear|helpful|great|excellent|amazing|awesome|love[d]?|like[d]?|good|nice)\b",
    re.IGNORECASE,
)


def _regex_extract_verbal_reason(transcript: str | None) -> str | None:
    """When the LLM extractor returns a null verbal_comment but the customer
    clearly stated WHY they gave a rating, pull a 1-2 sentence summary
    from the User: lines closest to the rating moment.

    Strategy: scan last 1500 chars for User: lines containing reason cues,
    take the most-recent up-to-2 short lines, join with ' / '.
    """
    if not transcript:
        return None
    tail = transcript[-1500:]
    lines = [ln.strip() for ln in tail.split("\n") if ln.strip().lower().startswith("user:")]
    matches: list[str] = []
    for ln in reversed(lines):
        body = ln.split(":", 1)[1].strip() if ":" in ln else ""
        if not body or len(body) < 4:
            continue
        if _REASON_CUES.search(body):
            matches.append(body[:120])
            if len(matches) >= 2:
                break
    if not matches:
        return None
    matches.reverse()
    return (" / ".join(matches))[:200]


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
            logger.warning("Post-call extraction did not return valid JSON - proceeding with regex fallbacks")
            structured = {}

        saved = None
        if structured:
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

        verbal_rating = structured.get("verbal_rating")
        try:
            verbal_rating = int(verbal_rating) if verbal_rating is not None else None
        except (ValueError, TypeError):
            verbal_rating = None
        if verbal_rating is not None and not (1 <= verbal_rating <= 5):
            verbal_rating = None

        verbal_comment_raw = structured.get("verbal_comment")
        verbal_comment = (str(verbal_comment_raw).strip() or None) if verbal_comment_raw else None

        # Regex fallback: smaller LLMs (Cerebras Llama 3.1 8B) sometimes miss
        # spoken-form ratings like "rate it as one" or "I'd say a 4".  If the
        # extractor returned null but the customer clearly named a 1-5, capture
        # it from the transcript tail.  Scans only the last 1500 chars (where
        # the closing feedback ask lives) to avoid catching unrelated numbers.
        if verbal_rating is None:
            verbal_rating = _regex_extract_verbal_rating(transcript)
            if verbal_rating is not None:
                logger.info(
                    "[PostCall] Regex fallback caught verbal_rating=%s for lead %s",
                    verbal_rating, lead_id,
                )

        if verbal_comment is None and verbal_rating is not None:
            reason = _regex_extract_verbal_reason(transcript)
            if reason:
                verbal_comment = reason
                logger.info(
                    "[PostCall] Regex fallback pulled reason for lead %s: %s",
                    lead_id, reason[:60],
                )

        if verbal_rating is not None or verbal_comment:
            try:
                from models.models import Feedback, utc_now
                from sqlmodel import select as _select
                existing = session.exec(
                    _select(Feedback).where(
                        Feedback.company_id == company_id,
                        Feedback.interaction_id == interaction_id,
                        Feedback.source == "customer",
                        Feedback.feedback_type == "csat",
                    ).limit(1)
                ).first()

                comment_text = verbal_comment or "Verbal rating given on call (no reason captured)"
                if existing:
                    existing.rating = verbal_rating if verbal_rating is not None else existing.rating
                    existing.comment = comment_text
                    existing.status = "submitted"
                    existing.responded_at = utc_now()
                    existing.updated_by = actor_user_id
                    session.add(existing)
                else:
                    session.add(Feedback(
                        company_id=company_id,
                        lead_id=lead_id,
                        interaction_id=interaction_id,
                        submitted_by_user_id=actor_user_id,
                        feedback_type="csat",
                        source="customer",
                        rating=verbal_rating,
                        comment=comment_text,
                        status="submitted",
                        responded_at=utc_now(),
                        created_by=actor_user_id,
                        updated_by=actor_user_id,
                    ))
                session.commit()
                logger.info(
                    "[PostCall] Verbal feedback saved for lead %s (rating=%s, comment=%s)",
                    lead_id, verbal_rating, (verbal_comment or '')[:40],
                )
            except Exception as fb_exc:
                logger.warning("[PostCall] Failed to save verbal feedback: %s", fb_exc)


        if structured.get("next_action") == "send_quote":
            try:
                from services.quote.voice_quote_service import auto_generate_and_send_quote
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


        _THROTTLE_SECONDS = 1.2

        await asyncio.sleep(_THROTTLE_SECONDS)

        try:
            from services.ai.llm import get_llm_service
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

        await asyncio.sleep(_THROTTLE_SECONDS)
        # AI Sales Coach — score the AI's performance and optionally auto-tune the system prompt
        try:
            from services.ai.llm import get_llm_service
            from services.call.call_coach_service import score_call_and_coach
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

        await asyncio.sleep(_THROTTLE_SECONDS)
        # Post-call competitor mention extraction (LLM, more accurate than real-time keywords)
        try:
            from services.ai.llm import get_llm_service
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

        try:
            from services.feedback.auto_csat_service import maybe_send_auto_csat
            qual = structured.get("qualification_status") or ""
            csat_outcome = (
                "answered_interested" if qual in ("qualified", "proposal")
                else "answered_callback_requested" if qual == "follow_up"
                else "answered_not_interested" if qual == "not_interested"
                else "answered_general"
            )
            maybe_send_auto_csat(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead_id,
                interaction_id=interaction_id,
                trigger="call",
                normalized_outcome=csat_outcome,
                channel="auto",
            )
        except Exception as csat_exc:
            logger.warning("[PostCall] CSAT dispatch failed: %s", csat_exc)

        try:
            from agents.orchestrator import run_post_call
            from models.models import Lead as _Lead

            lead_obj = session.get(_Lead, lead_id)

            raw_pain = structured.get("pain_points") or ""
            pain_list = [p.strip() for p in raw_pain.split(",") if p.strip()] if raw_pain else []
            raw_use = structured.get("use_case") or ""
            q_list = [raw_use] if raw_use else []

            qual = structured.get("qualification_status") or "neutral"

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
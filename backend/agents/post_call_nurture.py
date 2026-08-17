"""Post-Call Nurture Agents - Summarizer, CRM Updater, Writer"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlmodel import Session, select, text
from database import engine
from models.models import Interaction, Lead

import json
import logging
import re

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# LLM-driven transcript analysis
# ---------------------------------------------------------------------------

_SUMMARIZE_SYSTEM = (
    "You are a CRM data extraction assistant. "
    "Analyze the call transcript and extract structured insights. "
    "Return ONLY valid JSON — no markdown, no explanation outside JSON."
)

_SUMMARIZE_PROMPT = """Extract structured insights from this sales call transcript.

Pre-extracted data (from voice pipeline):
- Pain points: {pain_points}
- Questions asked by lead: {questions_asked}
- BANT: {bant}

Return JSON with exactly these keys:
{{
  "call_summary_text": "<2-3 sentence plain English summary of what happened>",
  "customer_intent": "<what the customer actually wants or is inquiring about>",
  "product_interest": "<specific product/service/category the customer asked about, or null>",
  "objections_raised": ["<objection 1>", "<objection 2>"],
  "buying_signals": ["<signal 1>", "<signal 2>"],
  "key_concerns": ["<concern 1>", "<concern 2>"],
  "next_step_agreed": "<what was agreed as the next step, or null>",
  "language_used": "<primary language spoken by the lead>"
}}

Rules:
- product_interest must come from the transcript — never invent product names.
- objections and buying_signals must be quoted or paraphrased from actual transcript lines.
- If data is absent, use null or empty list — do not fabricate.

TRANSCRIPT:
{transcript}"""


def _safe_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return None


def _resolve_llm_config(company_id: int) -> tuple[str, str, str] | None:
    """Return (provider, api_key, model) from company settings, or None."""
    try:
        from database import engine
        from sqlmodel import Session
        from credentials_service import get_company_setting_value

        with Session(engine) as s:
            def _g(k): return get_company_setting_value(s, company_id, k)

            explicit_provider = (_g("EVAL_JUDGE_PROVIDER") or "").lower().strip()
            explicit_model = (_g("EVAL_JUDGE_MODEL") or "").strip()

            key_map = {
                "mistral": _g("MISTRAL_API_KEY"),
                "groq":    _g("GROQ_API_KEY"),
                "openai":  _g("OPENAI_API_KEY"),
                "gemini":  _g("GEMINI_API_KEY"),
            }
            default_model = {
                "mistral": "mistral-large-latest",
                "groq":    "llama-3.1-8b-instant",
                "openai":  "gpt-4o-mini",
                "gemini":  "gemini-1.5-flash",
            }

            if explicit_provider and key_map.get(explicit_provider):
                provider = explicit_provider
            else:
                provider = next((p for p in ("mistral", "groq", "openai", "gemini") if key_map.get(p)), None)

            if not provider:
                return None

            return provider, key_map[provider], explicit_model or default_model[provider]
    except Exception as exc:
        logger.warning("[CallSummarizer] LLM config lookup failed: %s", exc)
        return None


def _call_llm_sync(provider: str, api_key: str, model: str, prompt: str) -> dict | None:
    """Sync LLM call — safe inside async context (no event loop conflict)."""
    messages = [
        {"role": "system", "content": _SUMMARIZE_SYSTEM},
        {"role": "user", "content": prompt},
    ]
    try:
        if provider == "mistral":
            from mistralai import Mistral
            client = Mistral(api_key=api_key)
            resp = client.chat.complete(
                model=model, messages=messages, temperature=0,
                max_tokens=800, response_format={"type": "json_object"},
            )
            return _safe_json(resp.choices[0].message.content)

        if provider in ("groq", "openai"):
            import openai
            base_url = "https://api.groq.com/openai/v1" if provider == "groq" else None
            kwargs = {"api_key": api_key}
            if base_url:
                kwargs["base_url"] = base_url
            client = openai.OpenAI(**kwargs)
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=0,
                max_tokens=800, response_format={"type": "json_object"},
            )
            return _safe_json(resp.choices[0].message.content)

        if provider == "gemini":
            try:
                from google import genai
                c = genai.Client(api_key=api_key)
                full = f"{_SUMMARIZE_SYSTEM}\n\n{prompt}"
                resp = c.models.generate_content(model=model, contents=full)
                return _safe_json(resp.text)
            except Exception:
                import google.generativeai as genai2  # type: ignore
                genai2.configure(api_key=api_key)
                m = genai2.GenerativeModel(model_name=model, system_instruction=_SUMMARIZE_SYSTEM)
                resp = m.generate_content(prompt)
                return _safe_json(resp.text)

    except Exception as exc:
        logger.warning("[CallSummarizer] LLM call failed (%s): %s", provider, exc)
    return None


def _llm_extract_insights(
    transcript: str,
    pain_points: list,
    questions_asked: list,
    bant_answers: dict,
    company_id: int,
) -> dict | None:
    config = _resolve_llm_config(company_id)
    if not config:
        return None
    provider, api_key, model = config
    prompt = _SUMMARIZE_PROMPT.format(
        pain_points=pain_points or [],
        questions_asked=questions_asked or [],
        bant=bant_answers or {},
        transcript=transcript[:4000],
    )
    result = _call_llm_sync(provider, api_key, model, prompt)
    if result:
        logger.info("[CallSummarizer] LLM extracted insights via %s/%s", provider, model)
    return result


# POST-CALL SUMMARIZER AGENT

class CallSummarizer:
    """
    Analyzes call transcript and extracts structured insights.
    Output is stored in CRM for future reference.
    """
    
    @staticmethod
    def summarize_call(
        lead_id: int,
        transcript: str,
        icp_score: float,
        sentiment: str,
        pain_points: List[str],
        questions_asked: List[str],
        bant_answers: Dict[str, Any],
        company_id: int = 0,
    ) -> dict:
        """LLM-driven call summary. Falls back to heuristic if no LLM configured."""
        # --- LLM extraction ---
        llm_insights = _llm_extract_insights(
            transcript=transcript,
            pain_points=pain_points,
            questions_asked=questions_asked,
            bant_answers=bant_answers,
            company_id=company_id,
        ) or {}

        # --- Heuristic fallback fields ---
        if not llm_insights.get("product_interest"):
            llm_insights["product_interest"] = (
                bant_answers.get("need")
                or bant_answers.get("product")
                or (pain_points[0] if pain_points else None)
            )

        if not llm_insights.get("objections_raised"):
            objection_kw = ["too expensive", "not interested", "competitor", "already have",
                            "budget", "not sure", "think about", "call back"]
            llm_insights["objections_raised"] = [kw for kw in objection_kw if kw in transcript.lower()]

        if not llm_insights.get("buying_signals"):
            buying_kw = ["interested", "want to", "sounds good", "tell me more",
                         "when can", "how much", "next steps", "demo"]
            llm_insights["buying_signals"] = [kw for kw in buying_kw if kw in transcript.lower()]

        summary = {
            "metadata": {
                "lead_id": lead_id,
                "call_date": datetime.now(timezone.utc).isoformat(),
                "transcript_preview": transcript[:500] + "..." if len(transcript) > 500 else transcript,
                "llm_driven": bool(llm_insights.get("call_summary_text")),
            },
            "qualification": {
                "icp_score": icp_score,
                "sentiment": sentiment,
                "qualified": icp_score > 0.75,
                "confidence": "high" if icp_score > 0.8 else "medium" if icp_score > 0.6 else "low",
            },
            "bant": bant_answers,
            "insights": {
                "call_summary_text": llm_insights.get("call_summary_text"),
                "customer_intent": llm_insights.get("customer_intent"),
                "pain_points": pain_points,
                "questions_asked": questions_asked,
                "objections_raised": llm_insights.get("objections_raised", []),
                "buying_signals": llm_insights.get("buying_signals", []),
                "key_concerns": llm_insights.get("key_concerns", []),
                "language_used": llm_insights.get("language_used"),
            },
            "recommendations": {
                "next_action": "book_demo" if icp_score > 0.75 else "send_followup",
                "suggested_product": llm_insights.get("product_interest"),
                "next_step_agreed": llm_insights.get("next_step_agreed"),
                "follow_up_days": 3 if sentiment == "positive" else 7,
            },
        }

        logger.info(
            "[Summarizer] lead=%s icp=%.2f llm_driven=%s product=%r",
            lead_id, icp_score, summary["metadata"]["llm_driven"],
            summary["recommendations"]["suggested_product"],
        )
        return summary
    
    @staticmethod
    def save_summary_to_crm(lead_id: int, summary: dict, company_id: int = 0, actor_user_id: int | None = None, parent_interaction_id: int | None = None) -> bool:
        """
        Save call summary to CRM interactions table.
        """
        try:
            with Session(engine) as session:
                interaction = Interaction(
                    company_id=company_id,
                    lead_id=lead_id,
                    user_id=actor_user_id,
                    type="call_summary",
                    channel="call",
                    direction="outbound",
                    source="voice_pipeline",
                    content=json.dumps(summary),
                    started_at=datetime.now(timezone.utc),
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                    parent_interaction_id=parent_interaction_id,
                )
                session.add(interaction)
                session.commit()

                print(f"✓ [SUMMARIZER] Summary saved to CRM for lead {lead_id}")
                return True
        except Exception as e:
            print(f"❌ [SUMMARIZER] Failed to save summary: {e}")
            return False

# CRM UPDATER AGENT

class CRMUpdater:
    """
    Updates lead record in CRM based on call outcome.
    Changes: status, enrichment_status, notes.
    """
    
    @staticmethod
    def update_lead_status(lead_id: int, new_status: str, notes: str = "") -> bool:
        """
        Update lead status in database.
        
        Args:
            lead_id: ID of the lead
            new_status: "New" | "Qualified" | "Demo Scheduled" | "Not Qualified" | "Closed"
            notes: Additional notes
        
        Returns:
            Success boolean
        """
        try:
            with Session(engine) as session:
                lead = session.get(Lead, lead_id)
                
                if not lead:
                    print(f"❌ [CRM_UPDATER] Lead {lead_id} not found")
                    return False
                
                old_status = lead.status
                lead.status = new_status
                
                # Update notes
                if notes:
                    lead.notes = (lead.notes or "") + f"\n[{datetime.now(timezone.utc).isoformat()}] {notes}"
                
                session.add(lead)
                session.commit()
                
                print(f"✓ [CRM_UPDATER] Lead {lead_id} status updated: {old_status} → {new_status}")
                return True
        except Exception as e:
            print(f"❌ [CRM_UPDATER] Failed to update lead: {e}")
            return False
    
    @staticmethod
    def log_interaction(lead_id: int, interaction_type: str, content: str, company_id: int = 0, actor_user_id: int | None = None) -> bool:
        """
        Log interaction to CRM.

        Args:
            lead_id: ID of the lead
            interaction_type: "call" | "email" | "note" | "demo_scheduled"
            content: Interaction content
            company_id: Company the lead belongs to
            actor_user_id: User performing the action

        Returns:
            Success boolean
        """
        try:
            with Session(engine) as session:
                interaction = Interaction(
                    company_id=company_id,
                    lead_id=lead_id,
                    user_id=actor_user_id,
                    type=interaction_type,
                    channel="call",
                    direction="outbound",
                    source="voice_pipeline",
                    content=content,
                    started_at=datetime.now(timezone.utc),
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
                session.add(interaction)
                session.commit()

                print(f"✓ [CRM_UPDATER] {interaction_type} logged for lead {lead_id}")
                return True
        except Exception as e:
            print(f"❌ [CRM_UPDATER] Failed to log interaction: {e}")
            return False

# EMAIL WRITER AGENT

class EmailWriter:
    """
    Generates personalized follow-up emails based on call insights.
    Uses call summary data to create highly relevant messages.
    """
    
    @staticmethod
    def generate_personalized_email(
        lead_name: str,
        company: str,
        pain_points: List[str],
        questions: List[str],
        icp_score: float,
        suggested_action: str,
    ) -> tuple:
        """
        Generate personalized follow-up email subject and body text.
        Does NOT include a greeting or sign-off — those are added by get_styled_html.

        Returns:
            (subject, body) tuple
        """
        if suggested_action == "book_demo":
            subject = "Let's set up your personalized demo"
        elif suggested_action == "discount_offer":
            subject = f"A special offer{' for ' + company if company else ''}"
        else:
            subject = "Following up from today's call"

        pain_html = "".join(f"<li>{p}</li>" for p in pain_points) if pain_points else ""

        parts = ["Thank you for speaking with our team today."]

        if pain_html:
            parts.append(f"<strong>Based on our conversation, we know you're working on:</strong><ul>{pain_html}</ul>")

        if suggested_action == "book_demo":
            parts.append(
                "We think a personalized demo would be a great next step — "
                "we'll tailor it specifically to your needs."
            )
        elif suggested_action == "discount_offer":
            parts.append(
                "We'd like to make this easy for you. We're offering "
                "<strong>15% off</strong> your first year when you sign up this month."
            )
        else:
            parts.append(
                "We'll follow up with resources tailored to your specific situation. "
                "Feel free to reply to this email anytime — we're here to help."
            )

        body = "\n\n".join(parts)

        print(f"📝 [EMAIL_WRITER] Generated personalized email for {lead_name}")
        print(f"   Subject: {subject}, Action: {suggested_action}")

        return subject, body
    
    @staticmethod
    def send_personalized_followup(
        session,
        company_id: int,
        actor_user_id: int,
        lead_id: int,
        lead_name: str,
        lead_email: str,
        company: str,
        pain_points: List[str],
        questions: List[str],
        icp_score: float,
        suggested_action: str,
        interaction_id: Optional[int] = None,
        parent_interaction_id: Optional[int] = None,
    ) -> bool:
        """
        Generate and send personalized follow-up email via communication_service.
        Attaches a CSAT feedback link as the email CTA.
        """
        try:
            from services.communication.communication_service import send_email_to_lead
            from services.feedback.csat_service import get_csat_base_url, get_or_create_pending_csat

            subject, body = EmailWriter.generate_personalized_email(
                lead_name, company, pain_points, questions, icp_score, suggested_action
            )

            # Create (or reuse) a pending CSAT record so we can embed a real feedback URL
            cta_url = ""
            cta_label = ""
            try:
                fb, _ = get_or_create_pending_csat(
                    session,
                    company_id=company_id,
                    lead_id=lead_id,
                    actor_user_id=actor_user_id,
                    interaction_id=interaction_id,
                )
                cta_url = f"{get_csat_base_url()}/feedback/{fb.token}"
                cta_label = "Share Your Feedback"
            except Exception as csat_exc:
                print(f"⚠️ [EMAIL_WRITER] Could not create CSAT record: {csat_exc}")

            result = send_email_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead_id,
                subject=subject,
                body=body,
                cta_url=cta_url,
                cta_label=cta_label,
                parent_interaction_id=parent_interaction_id,
            )

            print(f"✓ [EMAIL_WRITER] Email sent to {lead_email} | status: {result.get('status')}")
            return True
        except Exception as e:
            print(f"❌ [EMAIL_WRITER] Failed to send email: {e}")
            return False

# COMPLETE POST-CALL WORKFLOW

async def execute_post_call_nurture(
    lead_id: int,
    lead_data: dict,
    call_data: dict,
    company_id: int = 0,
    actor_user_id: Optional[int] = None,
    call_interaction_id: Optional[int] = None,
) -> dict:
    """
    Execute complete post-call nurture workflow.

    Args:
        lead_id: ID of the lead
        lead_data: {"name": str, "email": str, "company": str}
        call_data: {
            "transcript": str,
            "icp_score": float,
            "sentiment": str,
            "pain_points": List[str],
            "questions_asked": List[str],
            "bant_answers": dict,
            "call_outcome": str
        }
        company_id: Tenant ID (required for email dispatch)
        actor_user_id: User initiating the workflow

    Returns:
        Result dict with workflow execution details
    """
    result = {
        "lead_id": lead_id,
        "summary_saved": False,
        "status_updated": False,
        "email_sent": False,
        "errors": [],
    }

    try:
        # Summarize call
        summary = CallSummarizer.summarize_call(
            lead_id=lead_id,
            transcript=call_data["transcript"],
            icp_score=call_data["icp_score"],
            sentiment=call_data["sentiment"],
            pain_points=call_data["pain_points"],
            questions_asked=call_data["questions_asked"],
            bant_answers=call_data["bant_answers"],
        )
        result["summary_saved"] = CallSummarizer.save_summary_to_crm(
            lead_id, summary, company_id=company_id, actor_user_id=actor_user_id,
            parent_interaction_id=call_interaction_id,
        )

        # Update lead status
        new_status = "Qualified" if call_data["icp_score"] > 0.75 else "Not Qualified"
        notes = (
            f"Call outcome: {call_data['call_outcome']}. "
            f"ICP Score: {call_data['icp_score']}. "
            f"Sentiment: {call_data['sentiment']}."
        )
        result["status_updated"] = CRMUpdater.update_lead_status(lead_id, new_status, notes)

        # Send personalized follow-up email
        suggested_action = summary["recommendations"]["next_action"]
        with Session(engine) as session:
            result["email_sent"] = EmailWriter.send_personalized_followup(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead_id,
                lead_name=lead_data["name"],
                lead_email=lead_data["email"],
                company=lead_data.get("company", ""),
                pain_points=call_data["pain_points"],
                questions=call_data["questions_asked"],
                icp_score=call_data["icp_score"],
                suggested_action=suggested_action,
                parent_interaction_id=call_interaction_id,
            )

    except Exception as e:
        result["errors"].append(str(e))
        print(f"POST-CALL NURTURE ERROR: {e}")

    return result

if __name__ == "__main__":
    import asyncio
    
    # Test nurture workflow
    test_call_data = {
        "transcript": "Rio: Hi John... Lead: We need better lead management...",
        "icp_score": 0.85,
        "sentiment": "positive",
        "pain_points": ["Lead management", "Follow-up automation"],
        "questions_asked": ["Feature availability", "Pricing"],
        "bant_answers": {
            "budget": "$50k/year",
            "authority": "Decision maker",
            "need": "Lead management",
            "timeline": "Q1 2026"
        },
        "call_outcome": "positive"
    }
    
    test_lead_data = {
        "name": "John Smith",
        "email": "john@example.com",
        "company": "Tech Corp"
    }
    
    asyncio.run(execute_post_call_nurture(1, test_lead_data, test_call_data))

"""Post-Call Nurture Agents - Summarizer, CRM Updater, Writer"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlmodel import Session, select, text
from database import engine
from models.models import Interaction, Lead

import json

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
        bant_answers: Dict[str, Any]
    ) -> dict:
        """
        Create a comprehensive JSON summary of the call.
        
        Args:
            lead_id: ID of the lead
            transcript: Full call transcript
            icp_score: ICP qualification score (0-1)
            sentiment: "positive" | "neutral" | "negative"
            pain_points: List of pain points identified
            questions_asked: List of questions from lead
            bant_answers: Dict with BANT qualification answers
        
        Returns:
            Structured summary dict
        """
        summary = {
            "metadata": {
                "lead_id": lead_id,
                "call_date": datetime.now(timezone.utc).isoformat(),
                "transcript_preview": transcript[:500] + "..." if len(transcript) > 500 else transcript
            },
            "qualification": {
                "icp_score": icp_score,
                "sentiment": sentiment,
                "qualified": icp_score > 0.75,
                "confidence": "high" if icp_score > 0.8 else "medium" if icp_score > 0.6 else "low"
            },
            "bant": bant_answers,
            "insights": {
                "pain_points": pain_points,
                "questions_asked": questions_asked,
                "objections_raised": [],  # Would be extracted from transcript in production
                "buying_signals": []  # Would be extracted from transcript in production
            },
            "recommendations": {
                "next_action": "book_demo" if icp_score > 0.75 else "send_followup",
                "suggested_product": "Rio CRM Platform",  # In production: ML-based recommendation
                "follow_up_days": 3 if sentiment == "positive" else 7
            }
        }
        
        print(f"📊 [SUMMARIZER] Call summary created for lead {lead_id}")
        print(f"   ICP Score: {icp_score}, Sentiment: {sentiment}, Next: {summary['recommendations']['next_action']}")
        
        return summary
    
    @staticmethod
    def save_summary_to_crm(lead_id: int, summary: dict, company_id: int = 0, actor_user_id: int | None = None) -> bool:
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
    ) -> bool:
        """
        Generate and send personalized follow-up email via communication_service.
        Attaches a CSAT feedback link as the email CTA.
        """
        try:
            from services.communication_service import send_email_to_lead
            from services.csat_service import get_csat_base_url, get_or_create_pending_csat

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
    call_data: dict
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
    
    Returns:
        Result dict with workflow execution details
    """
    
    print(f"\n{'='*60}")
    print(f"🔄 STARTING POST-CALL NURTURE FOR: {lead_data['name']}")
    print(f"{'='*60}\n")
    
    result = {
        "lead_id": lead_id,
        "summary_saved": False,
        "status_updated": False,
        "email_sent": False,
        "errors": []
    }
    
    try:
        # Step 1: Summarize call
        summary = CallSummarizer.summarize_call(
            lead_id=lead_id,
            transcript=call_data["transcript"],
            icp_score=call_data["icp_score"],
            sentiment=call_data["sentiment"],
            pain_points=call_data["pain_points"],
            questions_asked=call_data["questions_asked"],
            bant_answers=call_data["bant_answers"]
        )
        result["summary_saved"] = CallSummarizer.save_summary_to_crm(lead_id, summary)
        
        # Step 2: Update lead status in CRM (no notes — outcomes go on Interaction, not lead.notes)
        new_status = "Qualified" if call_data["icp_score"] > 0.75 else "Not Qualified"
        notes = f"Call outcome: {call_data['call_outcome']}. ICP Score: {call_data['icp_score']}. Sentiment: {call_data['sentiment']}."
        result["status_updated"] = CRMUpdater.update_lead_status(lead_id, new_status, notes)
        
        # Step 3: Send personalized follow-up email
        suggested_action = summary["recommendations"]["next_action"]
        result["email_sent"] = EmailWriter.send_personalized_followup(
            lead_id=lead_id,
            lead_name=lead_data["name"],
            lead_email=lead_data["email"],
            company=lead_data["company"],
            pain_points=call_data["pain_points"],
            questions=call_data["questions_asked"],
            icp_score=call_data["icp_score"],
            suggested_action=suggested_action
        )
        
    except Exception as e:
        result["errors"].append(str(e))
        print(f"❌ POST-CALL NURTURE ERROR: {e}")
    
    print(f"\n{'='*60}")
    print(f"✓ POST-CALL NURTURE COMPLETE")
    print(f"Summary Saved: {result['summary_saved']}")
    print(f"Status Updated: {result['status_updated']}")
    print(f"Email Sent: {result['email_sent']}")
    print(f"{'='*60}\n")
    
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

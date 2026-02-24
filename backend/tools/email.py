import os
from datetime import datetime
from email_service import send_smtp_email, get_styled_html
from sqlmodel import Session, select
from database import engine
from models.models import Lead

from langchain_core.tools import tool

@tool
def send_followup_email(lead_id: int, template: str = "default", custom_data: dict = None) -> dict:
    """
    Send personalized follow-up email after call (DETERMINISTIC).
    
    Args:
        lead_id: ID of the lead
        template: Email template name ("default", "demo-booked", "not-qualified")
        custom_data: Custom variables for email template (name, product, time, etc.)
    
    Returns:
        {
            "sent": bool,
            "recipient": str,
            "template": str,
            "message": str
        }
    """
    with Session(engine) as session:
        lead = session.get(Lead, lead_id)
        
        if not lead or not lead.email:
            return {
                "sent": False,
                "error": f"Lead {lead_id} not found or has no email"
            }
        
        custom_data = custom_data or {}
        custom_data.setdefault("lead_name", lead.name)
        custom_data.setdefault("company", "Rio CRM")
        
        # Template selection
        templates = {
            "default": generate_default_template(custom_data),
            "demo-booked": generate_demo_booked_template(custom_data),
            "not-qualified": generate_not_qualified_template(custom_data),
            "discount-offer": generate_discount_offer_template(custom_data),
        }
        
        if template not in templates:
            return {
                "sent": False,
                "error": f"Template '{template}' not found"
            }
        
        subject, html_body = templates[template]
        
        try:
            send_smtp_email(
                recipient=lead.email,
                subject=subject,
                html_body=html_body,
                from_name="Rio Sales Team"
            )
            
            return {
                "sent": True,
                "recipient": lead.email,
                "template": template,
                "message": f"✓ {template} email sent to {lead.name}"
            }
        except Exception as e:
            return {
                "sent": False,
                "error": f"Failed to send email: {str(e)}"
            }

def generate_default_template(data: dict) -> tuple:
    """Generate default follow-up email template"""
    lead_name = data.get("lead_name", "Prospect")
    company = data.get("company", "Rio CRM")
    
    subject = f"Thank you for speaking with {company}"
    
    html = f"""
    <h2>Hi {lead_name},</h2>
    <p>Thank you for taking the time to speak with us today. We appreciated learning about your business and understanding your goals.</p>
    <p>Here are some resources we discussed:</p>
    <ul>
        <li>Our product overview: <a href="#">Link</a></li>
        <li>Case studies: <a href="#">Link</a></li>
        <li>Pricing guide: <a href="#">Link</a></li>
    </ul>
    <p>Feel free to reach out if you have any questions. We look forward to continuing the conversation!</p>
    <p>Best regards,<br/>Rio Sales Team</p>
    """
    
    return subject, html

def generate_demo_booked_template(data: dict) -> tuple:
    """Generate demo-booked confirmation email"""
    lead_name = data.get("lead_name", "Prospect")
    demo_time = data.get("demo_time", "soon")
    product = data.get("product", "our solution")
    
    subject = f"Your demo is confirmed! 🎉"
    
    html = f"""
    <h2>Demo Confirmed for {lead_name}</h2>
    <p>Excellent! We've scheduled your personalized demo of {product}.</p>
    <p><strong>Demo Details:</strong></p>
    <ul>
        <li>Time: {demo_time}</li>
        <li>Duration: 30 minutes</li>
        <li>Meeting link: <a href="#">Join Here</a></li>
    </ul>
    <p>We'll walk you through how {product} can help your team achieve better results.</p>
    <p>See you soon!<br/>Rio Sales Team</p>
    """
    
    return subject, html

def generate_not_qualified_template(data: dict) -> tuple:
    """Generate template for leads that don't meet ICP"""
    lead_name = data.get("lead_name", "Prospect")
    
    subject = "Resources to help your business"
    
    html = f"""
    <h2>Hi {lead_name},</h2>
    <p>Thank you for your interest. While your business may not be the perfect fit right now, we wanted to share some helpful resources:</p>
    <ul>
        <li><a href="#">Blog: Industry insights</a></li>
        <li><a href="#">Webinar: Best practices</a></li>
        <li><a href="#">Free tool: Business analyzer</a></li>
    </ul>
    <p>Feel free to reach out anytime. We're here to help!</p>
    <p>Best regards,<br/>Rio Sales Team</p>
    """
    
    return subject, html

def generate_discount_offer_template(data: dict) -> tuple:
    """Generate special discount offer email"""
    lead_name = data.get("lead_name", "Prospect")
    discount = data.get("discount_percent", "10")
    product = data.get("product", "our solution")
    
    subject = f"Special {discount}% offer for {lead_name}"
    
    html = f"""
    <h2>Exclusive Offer! 🎁</h2>
    <p>Hi {lead_name},</p>
    <p>Based on our conversation, we'd like to extend a special {discount}% discount on {product}.</p>
    <p>This offer is valid for 7 days.</p>
    <p><a href="#" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none;">Claim Offer</a></p>
    <p>Questions? Reply to this email anytime.</p>
    <p>Best regards,<br/>Rio Sales Team</p>
    """
    
    return subject, html

@tool
def send_personalized_email(lead_id: int, subject: str, html_body: str) -> dict:
    """
    Send completely custom email (DETERMINISTIC).
    
    Args:
        lead_id: ID of the lead
        subject: Email subject
        html_body: HTML body of email
    
    Returns:
        {"sent": bool, "recipient": str, "message": str}
    """
    with Session(engine) as session:
        lead = session.get(Lead, lead_id)
        
        if not lead or not lead.email:
            return {"sent": False, "error": f"Lead {lead_id} not found"}
        
        try:
            send_smtp_email(
                recipient=lead.email,
                subject=subject,
                html_body=html_body,
                from_name="Rio Sales Team"
            )
            
            return {
                "sent": True,
                "recipient": lead.email,
                "message": f"✓ Custom email sent to {lead.name}"
            }
        except Exception as e:
            return {
                "sent": False,
                "error": f"Failed to send email: {str(e)}"
            }

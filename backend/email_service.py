import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
from credentials_service import get_credential_smtp
import logging
from utils.encryption import decrypt_value

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_styled_html(subject: str, body: str, lead_name: str = "Valued Customer", user_id: int = None):
    """
    Wraps the body in a premium, modern HTML template.
    Uses user-specific company name and website if available.
    """
    from utils import settings_cache
    
    # Fetch user-specific or global defaults
    company_name = settings_cache.get("COMPANY_NAME", user_id) or "Rio CRM"
    company_website = settings_cache.get("COMPANY_WEBSITE", user_id) or "https://rio-crm.example.com/"

    # Create the clickable link
    company_link = f'<a href="{company_website}" style="color: inherit; text-decoration: none;">{company_name}</a>'
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 20px auto; border-radius: 24px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #7c3aed 0%, #2563eb 100%); padding: 40px 20px; text-align: center; color: white; }}
            .content {{ padding: 40px; background-color: #ffffff; }}
            .footer {{ background-color: #f8fafc; padding: 20px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #f1f5f9; }}
            .btn {{ display: inline-block; padding: 12px 24px; background: #7c3aed; color: white; text-decoration: none; border-radius: 12px; font-weight: bold; margin-top: 20px; }}
            h1 {{ margin: 0; font-size: 24px; letter-spacing: -0.5px; }}
            p {{ margin-bottom: 20px; }}
            a {{ color: #7c3aed; text-decoration: underline; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>{subject}</h1>
            </div>
            <div class="content">
                <p>Hi <strong>{lead_name}</strong>,</p>
                <div style="font-size: 16px; color: #475569;">
                    {body.replace('\\n', '<br>')}
                </div>
                <a href="{company_website}" class="btn">{company_name}</a>
                <p style="margin-top: 30px;">Best regards,<br><strong>Rio Digital Sales Representative</strong><br>{company_link} Team</p>
            </div>
            <div class="footer">
                &copy; 2026 {company_link}. All rights reserved.<br>
                Powered by Advanced Agentic Voice AI
            </div>
        </div>
    </body>
    </html>
    """

def send_smtp_email(to_email: str, subject: str, body: str, html_body: str = None, company_name: str = "Rio CRM", user_id: int = None):
    """
    Sends an email using SMTP settings from .env file or DB.
    Supports both plain text and HTML.
    """
    # Automatically decrypt if it's an encrypted blob
    to_email = decrypt_value(to_email)

    # smtp_server = os.getenv("SMTP_SERVER")
    # smtp_port = os.getenv("SMTP_PORT")
    # smtp_user = os.getenv("SMTP_USER")
    # smtp_password = os.getenv("SMTP_PASSWORD")
    # sender_email = os.getenv("SENDER_EMAIL")

    smtp_server   = get_credential_smtp("SMTP_SERVER", user_id)
    smtp_port     = int(get_credential_smtp("SMTP_PORT", user_id) or 587)
    smtp_user     = get_credential_smtp("SMTP_USERNAME", user_id)
    smtp_password = get_credential_smtp("SMTP_PASSWORD", user_id)
    sender_email    = get_credential_smtp("SMTP_FROM_EMAIL", user_id)

    if not all([smtp_server, smtp_port, smtp_user, smtp_password, sender_email]):
        logger.error("Missing SMTP configuration in .env.")
        logger.warning("SMTP configuration not found. Email will not be sent.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg['From'] = f"Rio from {company_name} <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = subject

        # Attach Plain Text
        msg.attach(MIMEText(body, 'plain'))
        
        # Attach HTML if provided
        if html_body:
            msg.attach(MIMEText(html_body, 'html'))

        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        logger.info(f"Premium Styled Email sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email: {str(e)}")
        return False

if __name__ == "__main__":
    # Test script (requires .env configuration)
    print("Testing Email Service...")
    success = send_smtp_email("test@example.com", "Rio Test Email", "This is a test email from the Rio Email Service.")
    if success:
        print("Test email sent!")
    else:
        print("Test email failed. Check .env configuration and console logs.")

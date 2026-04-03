import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)


def get_styled_html(
    subject: str,
    body: str,
    lead_name: str = "Valued Customer",
    company_name: str = "Rio CRM",
    company_website: str = "https://rio-crm.example.com/",
) -> str:
    company_link = f'<a href="{company_website}" style="color: inherit; text-decoration: none;">{company_name}</a>'
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 20px auto; border-radius: 24px; overflow: hidden; box-shadow: 0 10px 30px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #0f766e 0%, #1d4ed8 100%); padding: 32px 20px; text-align: center; color: white; }}
            .content {{ padding: 36px; background-color: #ffffff; }}
            .footer {{ background-color: #f8fafc; padding: 20px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid #f1f5f9; }}
            h1 {{ margin: 0; font-size: 24px; }}
            p {{ margin-bottom: 20px; }}
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
                    {body.replace("\\n", "<br>")}
                </div>
                <p style="margin-top: 30px;">Best regards,<br><strong>Rio Digital Sales Representative</strong><br>{company_link} Team</p>
            </div>
            <div class="footer">
                &copy; 2026 {company_link}. All rights reserved.
            </div>
        </div>
    </body>
    </html>
    """


def send_smtp_email(
    to_email: str,
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    company_name: str = "Rio CRM",
    smtp_host: Optional[str] = None,
    smtp_port: Optional[int] = None,
    smtp_username: Optional[str] = None,
    smtp_password: Optional[str] = None,
    smtp_from_email: Optional[str] = None,
) -> bool:
    to_email = decrypt_value(to_email)

    smtp_host = smtp_host or os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER")
    smtp_port = int(smtp_port or os.getenv("SMTP_PORT") or 587)
    smtp_username = smtp_username or os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER")
    smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")
    smtp_from_email = smtp_from_email or os.getenv("SMTP_FROM_EMAIL") or os.getenv("SENDER_EMAIL")

    if not all([smtp_host, smtp_port, smtp_username, smtp_password, smtp_from_email]):
        logger.warning("SMTP configuration is incomplete; email not sent")
        return False

    try:
        message = MIMEMultipart("alternative")
        message["From"] = f"Rio from {company_name} <{smtp_from_email}>"
        message["To"] = to_email
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))
        if html_body:
            message.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(message)

        logger.info("Email sent to %s", to_email)
        return True
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False

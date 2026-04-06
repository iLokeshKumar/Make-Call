import logging
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'(https?://[^\s<>"\']+)')


def _linkify(text: str) -> str:
    """Wrap bare http(s) URLs in <a> tags. Skips URLs already inside an HTML tag."""
    return _URL_RE.sub(
        lambda m: f'<a href="{m.group(1)}" style="color:#7c3aed;word-break:break-all;">{m.group(1)}</a>',
        text,
    )


def _cta_button(url: str, label: str) -> str:
    return f"""
    <div style="text-align:center;margin:32px 0;">
        <a href="{url}"
           style="display:inline-block;background:linear-gradient(135deg,#7c3aed,#2563eb);
                  color:#ffffff;text-decoration:none;font-weight:700;font-size:16px;
                  padding:14px 36px;border-radius:12px;letter-spacing:0.3px;
                  box-shadow:0 4px 15px rgba(124,58,237,0.4);">
            {label}
        </a>
        <p style="margin-top:16px;font-size:12px;color:#94a3b8;">
            If the button doesn't work, copy and paste this link into your browser:<br>
            <a href="{url}" style="color:#7c3aed;word-break:break-all;">{url}</a>
        </p>
    </div>"""


def get_styled_html(
    subject: str,
    body: str,
    lead_name: str = "Valued Customer",
    company_name: str = "Rio CRM",
    company_website: str = "https://rio-crm.example.com/",
    cta_url: str = "",
    cta_label: str = "",
) -> str:
    company_link = f'<a href="{company_website}" style="color:inherit;text-decoration:none;">{company_name}</a>'

    # Normalise newlines → <br>, then linkify any bare URLs left in the body
    rendered_body = _linkify(body.replace("\\n", "<br>").replace("\n", "<br>"))

    cta_html = _cta_button(cta_url, cta_label) if cta_url and cta_label else ""

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:'Segoe UI',Tahoma,Geneva,Verdana,sans-serif;line-height:1.6;color:#333;margin:0;padding:0;background:#f1f5f9;}}
  .wrap{{max-width:600px;margin:32px auto;border-radius:24px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,0.12);border:1px solid #e2e8f0;}}
  .hdr{{background:linear-gradient(135deg,#0f766e 0%,#1d4ed8 100%);padding:36px 24px;text-align:center;color:#fff;}}
  .hdr h1{{margin:0;font-size:22px;font-weight:800;letter-spacing:-0.3px;}}
  .body{{padding:36px;background:#fff;}}
  .footer{{background:#f8fafc;padding:20px;text-align:center;font-size:12px;color:#64748b;border-top:1px solid #f1f5f9;}}
  p{{margin-bottom:16px;}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr"><h1>{subject}</h1></div>
  <div class="body">
    <p>Hi <strong>{lead_name}</strong>,</p>
    <div style="font-size:15px;color:#475569;">{rendered_body}</div>
    {cta_html}
    <p style="margin-top:32px;border-top:1px solid #f1f5f9;padding-top:20px;">
      Best regards,<br><strong>Rio Digital Sales Representative</strong><br>{company_link} Team
    </p>
  </div>
  <div class="footer">&copy; 2026 {company_link}. All rights reserved.</div>
</div>
</body>
</html>"""


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

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)

        logger.info("Email sent to %s", to_email)
        return True
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False

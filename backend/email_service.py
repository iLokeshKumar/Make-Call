import logging
import mimetypes
import os
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

_URL_RE = re.compile(r'(https?://[^\s<>"\')\]]+)')


_SIGNOFF_RE = re.compile(
    r'\n{0,2}(best regards|regards|warm regards|sincerely|cheers|thanks|thank you)'
    r'[\s\S]*$',
    re.IGNORECASE,
)

_GREETING_RE = re.compile(
    r'^\s*(hi|hello|dear|hey)\b[^\n]{0,80}\n{1,3}',
    re.IGNORECASE,
)


def _linkify(text: str) -> str:
    """Wrap bare http(s) URLs in <a> tags. 
    
    Tries to skip URLs already inside an HTML tag (like in href or src) 
    by checking for a preceding quote or equals sign.
    """
    def _replace(m: re.Match) -> str:
        url = m.group(1)
        # Look behind in the original text to see if we're inside a tag attribute
        # This is a heuristic: if the URL is immediately preceded by '="' or '"', skip it.
        start = m.start()
        if start > 0 and text[start-1] in ('"', "'", "="):
            return m.group(0)
        
        return f'<a href="{url}" style="color:#7c3aed;word-break:break-all;">{url}</a>'

    return _URL_RE.sub(_replace, text)


def _markdown_table_to_html(text: str) -> str:
    """Convert markdown pipe-tables to styled HTML <table> blocks.

    Handles the standard format:
        | Header1 | Header2 |
        |---------|---------|
        | cell1   | cell2   |

    Must run BEFORE newline→<br> conversion.
    """
    _TABLE_RE = re.compile(
        r'(^\|.+\|[ \t]*\n'
        r'\|[\s:|-]+\|[ \t]*\n'
        r'(?:\|.+\|[ \t]*\n?)+)',
        re.MULTILINE,
    )

    _TH_STYLE = (
        'style="padding:10px 14px;text-align:left;font-size:13px;font-weight:700;'
        'color:#fff;background:linear-gradient(135deg,#0f766e,#1d4ed8);'
        'border-bottom:2px solid #e2e8f0;"'
    )
    _TD_STYLE = (
        'style="padding:10px 14px;font-size:13px;color:#334155;'
        'border-bottom:1px solid #f1f5f9;"'
    )
    _TD_ALT_STYLE = (
        'style="padding:10px 14px;font-size:13px;color:#334155;'
        'background:#f8fafc;border-bottom:1px solid #f1f5f9;"'
    )
    _TABLE_STYLE = (
        'style="width:100%;border-collapse:collapse;margin:16px 0;'
        'border-radius:12px;overflow:hidden;border:1px solid #e2e8f0;'
        'font-family:\'Segoe UI\',Tahoma,Geneva,Verdana,sans-serif;"'
    )

    def _parse_row(line: str) -> list[str]:
        cells = line.strip().strip("|").split("|")
        return [c.strip() for c in cells]

    def _convert(m: re.Match) -> str:
        lines = m.group(0).strip().splitlines()
        if len(lines) < 3:
            return m.group(0)

        headers = _parse_row(lines[0])
        # lines[1] is the separator — skip
        data_rows = [_parse_row(l) for l in lines[2:] if l.strip()]

        ths = "".join(f"<th {_TH_STYLE}>{h}</th>" for h in headers)
        thead = f"<thead><tr>{ths}</tr></thead>"

        body_rows = []
        for i, row in enumerate(data_rows):
            style = _TD_ALT_STYLE if i % 2 == 1 else _TD_STYLE
            tds = "".join(f"<td {style}>{c}</td>" for c in row)
            body_rows.append(f"<tr>{tds}</tr>")
        tbody = f"<tbody>{''.join(body_rows)}</tbody>"

        return f"<table {_TABLE_STYLE}>{thead}{tbody}</table>"

    return _TABLE_RE.sub(_convert, text)


def _markdown_to_html(text: str) -> str:
    """Convert a small subset of markdown to HTML suitable for email."""
    # Tables (must run before newline→<br> conversion):
    text = _markdown_table_to_html(text)
    
    # Markdown links: [text](url)
    text = re.sub(
        r'\[(.+?)\]\((https?://[^\s<>\")\]]+)\)', 
        r'<a href="\2" style="color:#7c3aed;text-decoration:none;font-weight:600;">\1</a>', 
        text
    )

    # Bold:
    text = re.sub(r'\*\*(?=\S)(.+?)(?<=\S)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'__(?=\S)(.+?)(?<=\S)__', r'<strong>\1</strong>', text)
    # Italic:
    text = re.sub(r'\*(?=\S)(.+?)(?<=\S)\*', r'<em>\1</em>', text)
    text = re.sub(r'\b_(?=\S)(.+?)(?<=\S)_\b', r'<em>\1</em>', text)
    # Headings:
    text = re.sub(r'^### (.+)$', r'<h3 style="margin:16px 0 6px;color:#1e293b;">\1</h3>', text, flags=re.MULTILINE)
    text = re.sub(r'^## (.+)$',  r'<h2 style="margin:20px 0 8px;color:#1e293b;">\1</h2>', text, flags=re.MULTILINE)
    text = re.sub(r'^# (.+)$',   r'<h1 style="margin:20px 0 8px;color:#1e293b;">\1</h1>', text, flags=re.MULTILINE)

    def _wrap_list(m: re.Match) -> str:
        items = re.sub(r'^[\-\*] ', '', m.group(0), flags=re.MULTILINE)
        lis = "".join(
            f'<li style="margin-bottom:4px;">{line.strip()}</li>'
            for line in items.splitlines()
            if line.strip()
        )
        return f'<ul style="padding-left:20px;margin:8px 0;">{lis}</ul>'
    text = re.sub(r'(^[\-\*] .+(\n[\-\*] .+)*)', _wrap_list, text, flags=re.MULTILINE)
    # Numbered lists:
    def _wrap_olist(m: re.Match) -> str:
        items = re.sub(r'^\d+\. ', '', m.group(0), flags=re.MULTILINE)
        lis = "".join(
            f'<li style="margin-bottom:4px;">{line.strip()}</li>'
            for line in items.splitlines()
            if line.strip()
        )
        return f'<ol style="padding-left:20px;margin:8px 0;">{lis}</ol>'
    text = re.sub(r'(^\d+\. .+(\n\d+\. .+)*)', _wrap_olist, text, flags=re.MULTILINE)
    # Newlines → <br> (after list/table conversion so we don't break blocks)
    text = text.replace("\\n", "\n").replace("\n", "<br>")
    return text


def _clean_llm_body(body: str, lead_name: str = "") -> str:
    """
    Strip duplicate greeting and sign-off that the LLM often adds,
    since the email template already provides both.
    """
    body = body.strip()
    
    body = _GREETING_RE.sub("", body).strip()
    
    body = _SIGNOFF_RE.sub("", body).strip()
    return body


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
    unsubscribe_url: str = "",
) -> str:
    company_link = f'<a href="{company_website}" style="color:inherit;text-decoration:none;">{company_name}</a>'

    cleaned = _clean_llm_body(body, lead_name)
    rendered_body = _linkify(_markdown_to_html(cleaned))

    cta_html = _cta_button(cta_url, cta_label) if cta_url and cta_label else ""

    unsub_html = (
        f'<br><a href="{unsubscribe_url}" style="color:#94a3b8;font-size:11px;">Unsubscribe</a>'
        if unsubscribe_url else ""
    )

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
  <div class="footer">&copy; 2026 {company_link}. All rights reserved.{unsub_html}</div>
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
    smtp_security: Optional[str] = None,  # "ssl" | "starttls" | "none"
    attachment_paths: Optional[list[str]] = None,
) -> bool:
    to_email = decrypt_value(to_email)

    smtp_host = smtp_host or os.getenv("SMTP_HOST") or os.getenv("SMTP_SERVER")
    smtp_port = int(smtp_port or os.getenv("SMTP_PORT") or 587)
    smtp_username = smtp_username or os.getenv("SMTP_USERNAME") or os.getenv("SMTP_USER")
    smtp_password = smtp_password or os.getenv("SMTP_PASSWORD")
    smtp_from_email = smtp_from_email or os.getenv("SMTP_FROM_EMAIL") or os.getenv("SENDER_EMAIL")
    smtp_security = (smtp_security or os.getenv("SMTP_SECURITY") or "").strip().lower()


    if smtp_security not in ("ssl", "starttls", "none"):
        smtp_security = "ssl" if smtp_port == 465 else "starttls"

    if not all([smtp_host, smtp_port, smtp_username, smtp_password, smtp_from_email]):
        logger.warning("SMTP configuration is incomplete; email not sent")
        return False

    try:
        message = MIMEMultipart("mixed")
        message["From"] = f"Rio from {company_name} <{smtp_from_email}>"
        message["To"] = to_email
        message["Subject"] = subject
        # Stamp the request_id (or worker trace_id) on the outbound mail so a support ticket → backend log walk works in either direction.  Falls back to "-" when no request context is set.
        try:
            from utils.logger import request_id_var
            req_id = request_id_var.get("-")
            if req_id and req_id != "-":
                message["X-Request-Id"] = req_id
        except Exception:  # noqa: BLE001
            pass
        alternative = MIMEMultipart("alternative")
        alternative.attach(MIMEText(body, "plain"))
        if html_body:
            alternative.attach(MIMEText(html_body, "html"))
        message.attach(alternative)

        for raw_path in attachment_paths or []:
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                logger.warning("Skipping missing email attachment: %s", raw_path)
                continue
            ctype, _ = mimetypes.guess_type(str(path))
            maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
            part = MIMEBase(maintype, subtype)
            part.set_payload(path.read_bytes())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", "attachment", filename=path.name)
            message.attach(part)

        if smtp_security == "ssl":
            with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        elif smtp_security == "starttls":
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.ehlo()
                server.starttls()
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)

        logger.info("Email sent to %s via %s:%s (%s)", to_email, smtp_host, smtp_port, smtp_security)
        return True
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)
        return False

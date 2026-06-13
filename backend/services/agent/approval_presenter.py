"""Approval payload presenter — turns AgentTask.input_json into reviewer-friendly text.

The approvals inbox used to render action_payload as raw JSON. That works for
engineers but operators shouldn't need to parse `{"template_id": 17}` — they
should see "Send email: Welcome email to Jane Doe" with a subject + body
preview. This module does that mapping per task_type.

The presenter is a pure function: given task_type + input_json + an optional
session (for looking up referenced entities like Leads and Quotes), return a
dict shaped for the UI.

Shape:
  {
    "title":        str,              # one-line what-this-does summary
    "description":  str,              # 2-3 line human explanation
    "preview":      dict | None,      # channel-specific preview, e.g.
                                      #   {"subject": ..., "body": ..., "to": ...}
    "warnings":     list[str],        # red flags the operator should read
                                      #   ("sends to 47 leads", "large quote: $50k")
    "raw":          dict,             # the original payload (for power users)
  }

Returning the raw payload under "raw" means the UI can keep the existing JSON
view as an advanced toggle — no loss of information.
"""
from __future__ import annotations

from typing import Any, Optional

from sqlmodel import Session, select

from models.models import Lead, ProposalDocument, ProposalRequest, Quote


def _truncate(text: str, limit: int = 240) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _lookup_lead_name(session: Optional[Session], company_id: int, lead_id: Optional[int]) -> str:
    """Best-effort: return 'Jane Doe (lead #42)' or 'lead #42' or 'unknown lead'."""
    if lead_id is None:
        return "unknown lead"
    if session is None:
        return f"lead #{lead_id}"
    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)
    ).first()
    if not lead:
        return f"lead #{lead_id}"
    return f"{lead.name} (lead #{lead_id})"


def _lookup_quote_summary(session: Optional[Session], company_id: int, quote_id: int) -> str:
    """Return 'Q-2024-001, total $12,500' or fallback."""
    if session is None:
        return f"quote #{quote_id}"
    quote = session.exec(
        select(Quote).where(Quote.id == quote_id, Quote.company_id == company_id)
    ).first()
    if not quote:
        return f"quote #{quote_id}"
    amount = f"{quote.currency} {quote.total_amount:,.2f}"
    return f"{quote.quote_number} — {amount}"


def _present_send_email(input_json: dict, session: Optional[Session], company_id: int, lead_id: Optional[int]) -> dict:
    subject = str(input_json.get("subject") or "")
    body = str(input_json.get("body") or "")
    cta_url = str(input_json.get("cta_url") or "")
    cta_label = str(input_json.get("cta_label") or "")
    lead_name = _lookup_lead_name(session, company_id, lead_id)

    return {
        "title": f"Send email to {lead_name}",
        "description": _truncate(subject, 120) or "(no subject)",
        "preview": {
            "channel": "email",
            "to": lead_name,
            "subject": subject,
            "body": _truncate(body, 800),
            "cta": f"{cta_label} → {cta_url}" if cta_url else None,
        },
        "warnings": [],
    }


def _present_send_whatsapp(input_json: dict, session: Optional[Session], company_id: int, lead_id: Optional[int]) -> dict:
    body = str(input_json.get("body") or "")
    lead_name = _lookup_lead_name(session, company_id, lead_id)

    warnings: list[str] = []
    if len(body) > 1000:
        warnings.append("Message body is over 1,000 characters — WhatsApp may truncate.")

    return {
        "title": f"Send WhatsApp to {lead_name}",
        "description": _truncate(body, 120) or "(empty message)",
        "preview": {
            "channel": "whatsapp",
            "to": lead_name,
            "body": _truncate(body, 800),
        },
        "warnings": warnings,
    }


def _present_send_quote(input_json: dict, session: Optional[Session], company_id: int, lead_id: Optional[int]) -> dict:
    quote_id = input_json.get("quote_id")
    channels = input_json.get("channels") or ["email"]
    subject = str(input_json.get("subject") or "")
    message = str(input_json.get("message") or "")
    lead_name = _lookup_lead_name(session, company_id, lead_id)

    quote_summary = (
        _lookup_quote_summary(session, company_id, int(quote_id))
        if isinstance(quote_id, int) or (isinstance(quote_id, str) and quote_id.isdigit())
        else "quote (unresolved id)"
    )

    warnings: list[str] = []
    # Quotes are high-value; flag any that would go to multiple channels simultaneously
    if len(channels) > 1:
        warnings.append(f"Will be sent on {len(channels)} channels: {', '.join(channels)}.")

    return {
        "title": f"Send {quote_summary} to {lead_name}",
        "description": (subject or message or "(default quote template)")[:160],
        "preview": {
            "channel": "quote",
            "to": lead_name,
            "quote": quote_summary,
            "channels": channels,
            "subject": subject,
            "message": _truncate(message, 400),
        },
        "warnings": warnings,
    }


def _present_send_proposal(input_json: dict, session: Optional[Session], company_id: int, lead_id: Optional[int]) -> dict:
    proposal_id = input_json.get("proposal_id")
    document_id = input_json.get("proposal_document_id")
    quote_id = input_json.get("quote_id")
    channels = input_json.get("channels") or ["email"]
    subject = str(input_json.get("subject") or "")
    message = str(input_json.get("message") or "")
    lead_name = _lookup_lead_name(session, company_id, lead_id)

    quote_summary = (
        _lookup_quote_summary(session, company_id, int(quote_id))
        if isinstance(quote_id, int) or (isinstance(quote_id, str) and quote_id.isdigit())
        else "quote pending"
    )

    warnings: list[str] = []
    validation = None
    if session and (isinstance(proposal_id, int) or (isinstance(proposal_id, str) and proposal_id.isdigit())):
        proposal = session.exec(
            select(ProposalRequest).where(
                ProposalRequest.id == int(proposal_id),
                ProposalRequest.company_id == company_id,
            )
        ).first()
        if proposal:
            validation = proposal.validation_json or {}
            warnings.extend(validation.get("warnings") or [])
            blockers = validation.get("blockers") or []
            warnings.extend(f"BLOCKER: {b}" for b in blockers)
    if session and (isinstance(document_id, int) or (isinstance(document_id, str) and document_id.isdigit())):
        doc = session.exec(
            select(ProposalDocument).where(
                ProposalDocument.id == int(document_id),
                ProposalDocument.company_id == company_id,
            )
        ).first()
        if doc and doc.status == "sent":
            warnings.append("This proposal document is already marked sent.")
        pdf_path = doc.pdf_path if doc else None
    else:
        pdf_path = None

    return {
        "title": f"Send proposal #{proposal_id} to {lead_name}",
        "description": f"{quote_summary} via {', '.join(channels)}",
        "preview": {
            "channel": "proposal",
            "to": lead_name,
            "proposal_id": proposal_id,
            "proposal_document_id": document_id,
            "quote": quote_summary,
            "channels": channels,
            "subject": subject,
            "message": _truncate(message, 400),
            "pdf_path": pdf_path,
            "validation": validation,
        },
        "warnings": warnings,
    }


# Presenter registry. Adding a new task_type is one entry here.
_PRESENTERS = {
    "send_email": _present_send_email,
    "send_whatsapp": _present_send_whatsapp,
    "send_quote": _present_send_quote,
    "send_proposal": _present_send_proposal,
}


def present(
    task_type: str,
    input_json: dict[str, Any],
    *,
    company_id: int,
    lead_id: Optional[int] = None,
    session: Optional[Session] = None,
) -> dict:
    """Return a presentation-friendly view of an approval payload.

    Falls back to a generic presenter for unknown task_types so operators
    always see something; unknown tasks just lose the per-type richness.

    session is optional — if None, entity lookups (lead name, quote number)
    degrade gracefully to ID-only strings. Useful for unit tests.
    """
    payload_copy = dict(input_json) if input_json else {}
    payload_copy.pop("summary", None)
    payload_copy.pop("task_type", None)

    presenter = _PRESENTERS.get(task_type)
    if presenter is None:
        return {
            "title": f"{task_type} (custom action)",
            "description": str(input_json.get("summary") or f"Task type: {task_type}"),
            "preview": None,
            "warnings": [],
            "raw": payload_copy,
        }

    result = presenter(input_json, session, company_id, lead_id)
    result["raw"] = payload_copy
    return result

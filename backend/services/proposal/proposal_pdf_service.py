from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Company, Lead, ProposalDocument, ProposalRequest, Quote, QuoteItem, utc_now
from services.proposal.proposal_service import get_proposal_or_404, latest_document


def _fmt_money(value, currency: str = "INR") -> str:
    try:
        return f"{currency} {float(value):,.2f}"
    except Exception:
        return f"{currency} {value}"


def _fmt_date(value) -> str:
    if not value:
        return "-"
    try:
        return value.strftime("%d %b %Y").lstrip("0")
    except Exception:
        return str(value)[:10]


def _first_text(value: Any, fallback: str = "-") -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v) or fallback
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items() if v) or fallback
    text = str(value).strip()
    return text or fallback


def generate_proposal_pdf(
    session: Session,
    company_id: int,
    actor_user_id: int,
    proposal_id: int,
    document_id: int | None = None,
    output_dir: str = "proposals",
) -> ProposalDocument:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    proposal = get_proposal_or_404(session, company_id, proposal_id)
    document = session.get(ProposalDocument, document_id) if document_id else latest_document(session, company_id, proposal_id)
    if not document or document.company_id != company_id:
        raise HTTPException(status_code=404, detail="Proposal document not found")

    lead = session.exec(select(Lead).where(Lead.id == proposal.lead_id, Lead.company_id == company_id)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    company = session.get(Company, company_id)
    quote = session.get(Quote, proposal.quote_id) if proposal.quote_id else None
    items = []
    if quote:
        items = session.exec(
            select(QuoteItem).where(QuoteItem.quote_id == quote.id, QuoteItem.company_id == company_id)
        ).all()

    spec = proposal.spec_json or {}
    solution = proposal.solution_json or {}
    validation = proposal.validation_json or {}
    scores = proposal.tabular_scores_json or {}
    sections = document.sections_json or {}

    company_name = company.name if company else "Rio CRM"
    brand_hex = (company.primary_color if company and company.primary_color else "#1e3a5f").lstrip("#")
    try:
        brand_color = colors.HexColor(f"#{brand_hex}")
    except Exception:
        brand_color = colors.HexColor("#1e3a5f")
    accent = colors.HexColor("#eef2ff")
    dark = colors.HexColor("#0f172a")
    muted = colors.HexColor("#64748b")
    line = colors.HexColor("#dbe4f0")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    file_path = Path(output_dir) / f"proposal_{proposal.id}_v{document.version}.pdf"

    page_w, _ = A4
    margin = 17 * mm
    inner_w = page_w - 2 * margin
    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=A4,
        leftMargin=margin,
        rightMargin=margin,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        title=document.title,
        author=company_name,
    )
    styles = getSampleStyleSheet()

    def sty(name: str, **kwargs):
        return ParagraphStyle(name, parent=styles["Normal"], **kwargs)

    h1 = sty("proposal_h1", fontName="Helvetica-Bold", fontSize=24, leading=29, textColor=colors.white)
    h2 = sty("proposal_h2", fontName="Helvetica-Bold", fontSize=13, leading=17, textColor=brand_color, spaceBefore=8, spaceAfter=5)
    h3 = sty("proposal_h3", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=dark)
    body = sty("proposal_body", fontSize=9.2, leading=13, textColor=dark)
    small = sty("proposal_small", fontSize=8, leading=11, textColor=muted)
    label = sty("proposal_label", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=muted)
    white_small = sty("proposal_white_small", fontSize=8.5, leading=12, textColor=colors.Color(1, 1, 1, 0.78))
    right = sty("proposal_right", fontSize=9, leading=12, textColor=dark, alignment=TA_RIGHT)
    center = sty("proposal_center", fontSize=8, leading=10, textColor=muted, alignment=TA_CENTER)

    story = []

    header_left = [
        [Paragraph("PROPOSAL", h1)],
        [Paragraph(document.title, white_small)],
        [Paragraph(f"Proposal #{proposal.id}  |  Version {document.version}", white_small)],
    ]
    company_lines = [company_name]
    if company and company.website:
        company_lines.append(company.website)
    if company and company.contact_email:
        company_lines.append(company.contact_email)
    if company and company.phone:
        company_lines.append(company.phone)
    company_text = "<br/>".join(company_lines)
    header_right = [[Paragraph(company_text, sty("company_white", fontName="Helvetica-Bold", fontSize=10, leading=14, textColor=colors.white, alignment=TA_RIGHT))]]
    header = Table(
        [[Table(header_left, colWidths=[inner_w * 0.58]), Table(header_right, colWidths=[inner_w * 0.42])]],
        colWidths=[inner_w * 0.58, inner_w * 0.42],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), brand_color),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header)
    story.append(Spacer(1, 6 * mm))

    buyer_rows = [
        [Paragraph("PREPARED FOR", label)],
        [Paragraph(lead.company_name or lead.name or f"Lead #{lead.id}", h3)],
        [Paragraph(" | ".join(filter(None, [lead.name if lead.company_name else None, lead.email, lead.normalized_phone])), body)],
        [Paragraph(", ".join(filter(None, [lead.city, lead.state, lead.country])), small)],
    ]
    meta_rows = [
        [Paragraph("COMMERCIAL SNAPSHOT", label)],
        [Paragraph(f"Intent: {_first_text(proposal.intent_type).upper()} ({float(proposal.intent_confidence):.0%})", body)],
        [Paragraph(f"Quote: {quote.quote_number if quote else '-'}", body)],
        [Paragraph(f"Total: {_fmt_money(quote.total_amount, quote.currency) if quote else '-'}", body)],
        [Paragraph(f"Valid until: {_fmt_date(quote.valid_until) if quote else '-'}", body)],
    ]
    top = Table(
        [[Table(buyer_rows, colWidths=[inner_w * 0.48]), Spacer(inner_w * 0.04, 1), Table(meta_rows, colWidths=[inner_w * 0.48])]],
        colWidths=[inner_w * 0.48, inner_w * 0.04, inner_w * 0.48],
    )
    top.setStyle(TableStyle([
        ("BOX", (0, 0), (0, 0), 0.5, line),
        ("BOX", (2, 0), (2, 0), 0.5, line),
        ("BACKGROUND", (0, 0), (0, 0), colors.white),
        ("BACKGROUND", (2, 0), (2, 0), accent),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(top)
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph("Executive Summary", h2))
    story.append(Paragraph(_first_text(sections.get("executive_summary")), body))

    story.append(Paragraph("Requirement Understanding", h2))
    req_rows = [
        ["Buyer problem", _first_text(spec.get("buyer_problem"))],
        ["Required products", _first_text(spec.get("required_products"))],
        ["Quantities", _first_text(spec.get("quantities"))],
        ["Timeline", _first_text(spec.get("timeline"))],
        ["Budget", _first_text(spec.get("budget_range"))],
        ["Delivery location", _first_text(spec.get("delivery_location"))],
    ]
    req_table = Table(
        [[Paragraph(k, label), Paragraph(v, body)] for k, v in req_rows],
        colWidths=[inner_w * 0.25, inner_w * 0.75],
    )
    req_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.35, line),
        ("BACKGROUND", (0, 0), (0, -1), accent),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(req_table)

    story.append(Paragraph("Recommended Solution", h2))
    sol_rows = [[Paragraph("Requested", label), Paragraph("Recommended", label), Paragraph("Qty", label), Paragraph("Rationale", label)]]
    for rec in solution.get("recommended_items") or []:
        match = rec.get("matched")
        sol_rows.append([
            Paragraph(_first_text(rec.get("requested")), body),
            Paragraph(_first_text(match.get("name") if match else "Manual review required"), body),
            Paragraph(str(match.get("quantity") if match else "-"), body),
            Paragraph(_first_text(rec.get("reason")), small),
        ])
    if len(sol_rows) == 1:
        sol_rows.append([Paragraph("-", body), Paragraph("No solution items matched", body), Paragraph("-", body), Paragraph("-", body)])
    sol_table = Table(sol_rows, colWidths=[inner_w * 0.26, inner_w * 0.34, inner_w * 0.08, inner_w * 0.32], repeatRows=1)
    sol_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), brand_color),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, line),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, accent]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(sol_table)

    if items:
        story.append(Paragraph("Commercial Offer", h2))
        offer_rows = [[Paragraph("Item", label), Paragraph("SKU", label), Paragraph("Qty", label), Paragraph("Unit", label), Paragraph("Total", label)]]
        for item in items:
            offer_rows.append([
                Paragraph(item.product_name_snapshot, body),
                Paragraph(item.sku_snapshot or "-", small),
                Paragraph(str(item.quantity), right),
                Paragraph(_fmt_money(item.unit_price, quote.currency), right),
                Paragraph(_fmt_money(item.line_total, quote.currency), right),
            ])
        offer_rows.append(["", "", "", Paragraph("TOTAL", h3), Paragraph(_fmt_money(quote.total_amount, quote.currency), sty("grand", fontName="Helvetica-Bold", fontSize=11, textColor=brand_color, alignment=TA_RIGHT))])
        offer = Table(offer_rows, colWidths=[inner_w * 0.40, inner_w * 0.15, inner_w * 0.08, inner_w * 0.17, inner_w * 0.20], repeatRows=1)
        offer.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), brand_color),
            ("GRID", (0, 0), (-1, -2), 0.35, line),
            ("LINEABOVE", (3, -1), (-1, -1), 1.0, brand_color),
            ("BACKGROUND", (3, -1), (-1, -1), accent),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        story.append(offer)

    story.append(PageBreak())
    story.append(Paragraph("Risk, Validation, and Decision Support", h2))
    score_rows = [
        ["Prediction provider", _first_text(scores.get("provider"))],
        ["Win probability", f"{float(scores.get('win_probability') or 0):.0%}"],
        ["Pricing risk", _first_text(scores.get("pricing_risk"))],
        ["Missing requirement risk", f"{float(scores.get('missing_requirement_risk') or 0):.0%}"],
        ["Recommended discount", f"{float(scores.get('recommended_discount_percent') or 0):.1f}%"],
    ]
    story.append(Table([[Paragraph(k, label), Paragraph(v, body)] for k, v in score_rows], colWidths=[inner_w * 0.35, inner_w * 0.65], style=[
        ("GRID", (0, 0), (-1, -1), 0.35, line),
        ("BACKGROUND", (0, 0), (0, -1), accent),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(Paragraph("Validation Checklist", h2))
    blockers = validation.get("blockers") or []
    warnings = validation.get("warnings") or []
    status_text = validation.get("status") or "unknown"
    checklist = [["Status", status_text], ["Blockers", _first_text(blockers, "None")], ["Warnings", _first_text(warnings, "None")]]
    story.append(Table([[Paragraph(k, label), Paragraph(v, body)] for k, v in checklist], colWidths=[inner_w * 0.22, inner_w * 0.78], style=[
        ("GRID", (0, 0), (-1, -1), 0.35, line),
        ("BACKGROUND", (0, 0), (0, -1), accent),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))

    story.append(Paragraph("Assumptions and Next Steps", h2))
    assumptions = solution.get("assumptions") or sections.get("assumptions") or []
    for item in assumptions or ["Commercials are subject to final stock, tax, and delivery confirmation."]:
        story.append(Paragraph(f"- {item}", body))
    for item in sections.get("next_steps") or []:
        story.append(Paragraph(f"- {item}", body))

    story.append(Spacer(1, 8 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=line))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(f"Generated by Rio CRM for {company_name}", center))

    doc.build(story)

    document.pdf_path = str(file_path)
    document.updated_at = utc_now()
    document.updated_by = actor_user_id
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


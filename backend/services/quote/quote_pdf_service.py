from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Company, Lead, Quote, QuoteItem, utc_now
from services.leads.engagement_service import record_quote_event
from services.quote.quote_service import get_quote_or_404

logger = logging.getLogger(__name__)


def _fmt_currency(amount, currency: str) -> str:
    try:
        return f"{currency} {float(amount):,.2f}"
    except Exception:
        return f"{currency} {amount}"


def generate_quote_pdf(
    session: Session,
    company_id: int,
    actor_user_id: int,
    quote_id: int,
    output_dir: str = "quotes",
) -> Quote:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        HRFlowable, Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )

    quote = get_quote_or_404(session, company_id, quote_id)

    lead = session.exec(
        select(Lead).where(Lead.id == quote.lead_id, Lead.company_id == company_id)
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    items = session.exec(
        select(QuoteItem).where(
            QuoteItem.quote_id == quote.id, QuoteItem.company_id == company_id
        )
    ).all()
    if not items:
        raise HTTPException(status_code=400, detail="Quote has no items")

    company = session.exec(select(Company).where(Company.id == company_id)).first()
    company_name = company.name if company else "Rio CRM"
    company_website = company.website if company and company.website else ""
    brand_hex = (company.primary_color or "#1e3a5f").lstrip("#")
    try:
        brand_r = int(brand_hex[0:2], 16) / 255
        brand_g = int(brand_hex[2:4], 16) / 255
        brand_b = int(brand_hex[4:6], 16) / 255
        brand_color = colors.Color(brand_r, brand_g, brand_b)
    except Exception:
        brand_color = colors.HexColor("#1e3a5f")

    accent_color = colors.HexColor("#f0f4ff")
    total_bg     = colors.HexColor("#eef2ff")
    header_text  = colors.white
    muted        = colors.HexColor("#64748b")
    dark         = colors.HexColor("#0f172a")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    file_path = Path(output_dir) / f"{quote.quote_number}.pdf"

    PAGE_W, PAGE_H = A4
    M = 18 * mm

    doc = SimpleDocTemplate(
        str(file_path),
        pagesize=A4,
        leftMargin=M, rightMargin=M,
        topMargin=M, bottomMargin=14 * mm,
        title=f"Quotation {quote.quote_number}",
        author=company_name,
    )

    styles = getSampleStyleSheet()

    def sty(name, **kw):
        return ParagraphStyle(name, parent=styles["Normal"], **kw)

    s_h1        = sty("h1",   fontSize=22, fontName="Helvetica-Bold", textColor=header_text, leading=26)
    s_h1sub     = sty("h1s",  fontSize=9,  fontName="Helvetica",      textColor=colors.Color(1,1,1,0.75), leading=12)
    s_label     = sty("lbl",  fontSize=7.5, fontName="Helvetica-Bold", textColor=muted,  spaceBefore=0, leading=10, spaceAfter=0)
    s_value     = sty("val",  fontSize=9.5, fontName="Helvetica",      textColor=dark,   spaceBefore=0, leading=12, spaceAfter=0)
    s_th        = sty("th",   fontSize=8,  fontName="Helvetica-Bold",  textColor=header_text, leading=10)
    s_td        = sty("td",   fontSize=9,  fontName="Helvetica",       textColor=dark,   leading=12)
    s_td_muted  = sty("tdm",  fontSize=8,  fontName="Helvetica",       textColor=muted,  leading=10)
    s_total_lbl = sty("tl",   fontSize=9,  fontName="Helvetica-Bold",  textColor=muted,  leading=12)
    s_total_val = sty("tv",   fontSize=9,  fontName="Helvetica",       textColor=dark,   leading=12, alignment=2)
    s_grand_lbl = sty("gl",   fontSize=11, fontName="Helvetica-Bold",  textColor=brand_color, leading=14)
    s_grand_val = sty("gv",   fontSize=11, fontName="Helvetica-Bold",  textColor=brand_color, leading=14, alignment=2)
    s_note      = sty("note", fontSize=8.5, fontName="Helvetica",      textColor=muted,  leading=12)
    s_footer    = sty("ftr",  fontSize=7.5, fontName="Helvetica",      textColor=muted,  leading=10, alignment=1)

    story = []
    inner_w = PAGE_W - 2 * M

    # HEADER BAND.  strftime("%-d") is GNU-only; on Windows it raises
    # ValueError.  Use "%d" (zero-padded) and strip the leading 0 manually
    # so the format works on Linux, macOS, and Windows.
    def _fmt_date(dt):
        if not hasattr(dt, "strftime"):
            return str(dt)[:10]
        return dt.strftime("%d %b %Y").lstrip("0")

    issued_str = _fmt_date(quote.created_at)
    valid_str  = _fmt_date(quote.valid_until) if quote.valid_until else "—"

    header_left = [
        [Paragraph("QUOTATION", s_h1)],
        [Paragraph(f"# {quote.quote_number}", s_h1sub)],
        [Spacer(1, 4)],
        [Paragraph(f"Issued: {issued_str}  ·  Valid until: {valid_str}", s_h1sub)],
    ]
    co_lines = [company_name]
    if company and company.address:
        co_lines.append(company.address)
    loc_parts = list(filter(None, [
        company.city if company else None,
        company.state if company else None,
        company.pincode if company else None,
        company.country if company else None,
    ]))
    if loc_parts:
        co_lines.append(", ".join(loc_parts))
    if company and company.phone:
        co_lines.append(company.phone)
    if company and company.contact_email:
        co_lines.append(company.contact_email)
    if company_website:
        co_lines.append(company_website)
    # Tax / legal identifiers
    tax_parts = []
    if company and company.gst_number:
        tax_parts.append(f"GST: {company.gst_number}")
    if company and company.pan_number:
        tax_parts.append(f"PAN: {company.pan_number}")
    if company and company.vat_number:
        tax_parts.append(f"VAT: {company.vat_number}")
    if company and company.cin_number:
        tax_parts.append(f"CIN: {company.cin_number}")
    if tax_parts:
        co_lines.append("  ·  ".join(tax_parts))

    co_text = "<br/>".join(co_lines[1:])
    s_cn = sty("cn", fontSize=13, fontName="Helvetica-Bold", textColor=header_text, alignment=2, leading=17)
    s_cw = sty("cw", fontSize=7.5, fontName="Helvetica", textColor=colors.Color(1, 1, 1, 0.75), alignment=2, leading=11)

    header_right_content = []
    # Try to embed company logo if available
    logo_url = company.logo_url if company else None
    if logo_url:
        try:
            import urllib.request, tempfile, os as _os
            logo_path = None
            if logo_url.startswith("http"):
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
                urllib.request.urlretrieve(logo_url, tmp.name)
                logo_path = tmp.name
            elif _os.path.exists(logo_url):
                logo_path = logo_url
            if logo_path:
                img = Image(logo_path, width=inner_w * 0.20, height=18 * mm, kind="proportional")
                img.hAlign = "RIGHT"
                header_right_content.append([img])
                header_right_content.append([Spacer(1, 4)])
        except Exception:
            pass  # logo load failed — skip silently

    header_right_content.append([Paragraph(co_lines[0], s_cn)])
    header_right_content.append([Spacer(1, 3)])
    header_right_content.append([Paragraph(co_text, s_cw)])

    header_tbl = Table(
        [[Table(header_left, colWidths=[inner_w * 0.55]),
          Table(header_right_content, colWidths=[inner_w * 0.45])]],
        colWidths=[inner_w * 0.55, inner_w * 0.45],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), brand_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING",   (0, 0), (0, -1), 16),
        ("RIGHTPADDING",  (-1, 0), (-1, -1), 16),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(header_tbl)
    story.append(Spacer(1, 6 * mm))

    # BILL TO / QUOTE DETAILS
    bill_to_header = [[Paragraph("BILL TO", sty("bth", fontSize=8, fontName="Helvetica-Bold",
                                                 textColor=brand_color, leading=10))]]
    bill_rows = []
    s_bn  = sty("bn",  fontSize=11, fontName="Helvetica-Bold", textColor=dark, leading=14)
    s_tax = sty("lgst", fontSize=8.5, fontName="Helvetica-Bold", textColor=dark, leading=11)

    # Company name (B2B) or lead name as primary heading
    if lead.company_name:
        bill_rows.append([Paragraph(lead.company_name, s_bn)])
        # Contact person line: name · designation/job_title
        role = lead.designation or lead.job_title or ""
        person_line = " · ".join(filter(None, [lead.name, role]))
        if person_line:
            bill_rows.append([Paragraph(person_line, s_value)])
    else:
        bill_rows.append([Paragraph(lead.name or "—", s_bn)])
        role = lead.designation or lead.job_title or ""
        if role:
            bill_rows.append([Paragraph(role, s_value)])

    # Contact details
    if lead.email:
        bill_rows.append([Paragraph(lead.email, s_value)])
    if lead.normalized_phone:
        bill_rows.append([Paragraph(lead.normalized_phone, s_value)])
    if lead.website:
        bill_rows.append([Paragraph(lead.website, s_value)])

    # Address — prefer billing_address; fall back to city/state/pincode/country
    if lead.billing_address:
        bill_rows.append([Paragraph(lead.billing_address, s_value)])
    addr_parts = list(filter(None, [lead.city, lead.state, lead.pincode, lead.country]))
    if addr_parts:
        bill_rows.append([Paragraph(", ".join(addr_parts), s_value)])

    # Industry
    if lead.industry:
        bill_rows.append([Paragraph(f"Industry: {lead.industry}", s_value)])

    # Tax identifiers
    lead_tax = []
    if lead.gst_number:
        lead_tax.append(f"GST: {lead.gst_number}")
    if lead_tax:
        bill_rows.append([Paragraph("  ·  ".join(lead_tax), s_tax)])

    bill_tbl = Table(bill_to_header + bill_rows, colWidths=[inner_w * 0.48])
    bill_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, brand_color),
        ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))

    meta_rows = [
        [Paragraph("QUOTE DETAILS", sty("qdt", fontSize=8, fontName="Helvetica-Bold",
                                         textColor=brand_color, leading=10))],
    ]
    for lbl, val in [
        ("Quote Number", quote.quote_number),
        ("Status",       quote.status.capitalize()),
        ("Currency",     quote.currency),
        ("Valid Until",  valid_str),
    ]:
        meta_rows.append([
            Table([[Paragraph(lbl, s_label), Paragraph(val, s_value)]],
                  colWidths=[inner_w * 0.22, inner_w * 0.22],
                  style=[("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),
                         ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0)])
        ])

    meta_tbl = Table(meta_rows, colWidths=[inner_w * 0.48])
    meta_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), accent_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 10),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, brand_color),
        ("BOX",  (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
    ]))

    two_col = Table(
        [[bill_tbl, Spacer(inner_w * 0.04, 1), meta_tbl]],
        colWidths=[inner_w * 0.48, inner_w * 0.04, inner_w * 0.48],
    )
    two_col.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 0),
    ]))
    story.append(two_col)
    story.append(Spacer(1, 6 * mm))

    # LINE ITEMS TABLE
    col_w = [
        inner_w * 0.05,
        inner_w * 0.32,
        inner_w * 0.10,
        inner_w * 0.08,
        inner_w * 0.15,
        inner_w * 0.10,
        inner_w * 0.20,
    ]
    tbl_data = [[
        Paragraph("#",          s_th),
        Paragraph("Product",    s_th),
        Paragraph("SKU",        s_th),
        Paragraph("Qty",        s_th),
        Paragraph("Unit Price", s_th),
        Paragraph("Discount",   s_th),
        Paragraph("Total",      sty("thr", fontSize=8, fontName="Helvetica-Bold",
                                    textColor=header_text, leading=10, alignment=2)),
    ]]

    tbl_style = [
        ("BACKGROUND",    (0, 0), (-1, 0), brand_color),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, accent_color]),
        ("LINEBELOW",     (0, 0), (-1, -2), 0.3, colors.HexColor("#e2e8f0")),
        ("LINEBELOW",     (0, -1), (-1, -1), 0.3, colors.HexColor("#e2e8f0")),
        ("ALIGN",         (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN",         (0, 0), (0, -1), "CENTER"),
    ]

    for idx, item in enumerate(items, start=1):
        disc_str = f"{float(item.discount_percent):.1f}%" if float(item.discount_percent) > 0 else "—"
        row = [
            Paragraph(str(idx), sty("ri", fontSize=9, fontName="Helvetica", textColor=muted, leading=12, alignment=1)),
            [
                Paragraph(item.product_name_snapshot, s_td),
                Paragraph(item.notes or "", s_td_muted) if item.notes else Spacer(1, 0),
            ],
            Paragraph(item.sku_snapshot or "—", s_td_muted),
            Paragraph(str(item.quantity), sty("qty", fontSize=9, fontName="Helvetica", textColor=dark, leading=12, alignment=2)),
            Paragraph(_fmt_currency(item.unit_price, quote.currency), sty("up", fontSize=9, fontName="Helvetica", textColor=dark, leading=12, alignment=2)),
            Paragraph(disc_str, sty("dc", fontSize=9, fontName="Helvetica", textColor=colors.HexColor("#10b981") if float(item.discount_percent) > 0 else muted, leading=12, alignment=2)),
            Paragraph(_fmt_currency(item.line_total, quote.currency), sty("lt", fontSize=9, fontName="Helvetica-Bold", textColor=dark, leading=12, alignment=2)),
        ]
        tbl_data.append(row)

    items_tbl = Table(tbl_data, colWidths=col_w, repeatRows=1)
    items_tbl.setStyle(TableStyle(tbl_style))
    story.append(items_tbl)
    story.append(Spacer(1, 4 * mm))

    # TOTALS
    totals_data = []
    if float(quote.subtotal) != float(quote.total_amount):
        totals_data.append(["Subtotal",  _fmt_currency(quote.subtotal, quote.currency)])
    if float(quote.discount_amount) > 0:
        totals_data.append(["Discount",  f"- {_fmt_currency(quote.discount_amount, quote.currency)}"])
    if float(quote.tax_amount) > 0:
        totals_data.append(["Tax / GST", _fmt_currency(quote.tax_amount, quote.currency)])

    totals_rows = [
        [Paragraph(lbl, s_total_lbl), Paragraph(val, s_total_val)]
        for lbl, val in totals_data
    ]
    totals_rows.append([
        Paragraph("TOTAL", s_grand_lbl),
        Paragraph(_fmt_currency(quote.total_amount, quote.currency), s_grand_val),
    ])

    totals_tbl = Table(
        totals_rows,
        colWidths=[inner_w * 0.18, inner_w * 0.18],
        hAlign="RIGHT",
    )
    totals_ts = [
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("LINEABOVE",     (0, -1), (-1, -1), 1.0, brand_color),
        ("BACKGROUND",    (0, -1), (-1, -1), total_bg),
        ("ROUNDEDCORNERS", [4]),
    ]
    totals_tbl.setStyle(TableStyle(totals_ts))
    story.append(totals_tbl)

    # NOTES
    if quote.notes:
        story.append(Spacer(1, 6 * mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
        story.append(Spacer(1, 3 * mm))
        story.append(Paragraph("Notes & Terms", sty("nt", fontSize=9, fontName="Helvetica-Bold",
                                                      textColor=brand_color, leading=12)))
        story.append(Spacer(1, 2 * mm))
        story.append(Paragraph(quote.notes.replace("\n", "<br/>"), s_note))

    # FOOTER
    story.append(Spacer(1, 10 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 3 * mm))
    footer_parts = [f"Thank you for your business, {lead.name or 'valued customer'}!"]
    if company_website:
        footer_parts.append(company_website)
    story.append(Paragraph("  ·  ".join(footer_parts), s_footer))

    doc.build(story)

    quote.pdf_path = str(file_path)
    quote.updated_at = utc_now()
    quote.updated_by = actor_user_id
    session.add(quote)
    session.commit()
    session.refresh(quote)
    record_quote_event(
        session=session,
        company_id=company_id,
        quote_id=quote.id,
        event_type="pdf_generated",
        payload={"pdf_path": quote.pdf_path},
    )
    return quote

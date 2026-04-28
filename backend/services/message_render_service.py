import re
from sqlmodel import Session, select

from models.models import Company, Lead, MessageTemplate, Product, Quote


PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")


def build_template_context(
    session: Session,
    company_id: int,
    lead_id: int | None = None,
    quote_id: int | None = None,
    product_id: int | None = None,
) -> dict:
    context = {}

    company = session.exec(
        select(Company).where(Company.id == company_id)
    ).first()
    if company:
        context["company_name"] = company.name
        context["company_slug"] = company.slug
        context["company_website"] = company.website or ""

    if lead_id:
        lead = session.exec(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.company_id == company_id,
            )
        ).first()
        if lead:
            context["lead_name"] = lead.name
            context["lead_email"] = lead.email or ""
            context["lead_phone"] = lead.normalized_phone or ""
            context["lead_status"] = lead.status or ""
            context["lead_city"] = lead.city or ""
            context["lead_state"] = lead.state or ""
            context["lead_industry"] = lead.industry or ""

    if quote_id:
        quote = session.exec(
            select(Quote).where(
                Quote.id == quote_id,
                Quote.company_id == company_id,
                Quote.deleted_at.is_(None),
            )
        ).first()
        if quote:
            context["quote_number"] = quote.quote_number
            context["quote_total"] = str(quote.total_amount)
            context["quote_currency"] = quote.currency
            context["quote_status"] = quote.status

    if product_id:
        product = session.exec(
            select(Product).where(
                Product.id == product_id,
                Product.company_id == company_id,
            )
        ).first()
        if product:
            context["product_name"] = product.name
            context["product_sku"] = product.sku or ""
            context["product_price"] = str(product.price)

    return context


def render_text(template_text: str, context: dict) -> str:
    def replacer(match):
        key = match.group(1)
        return str(context.get(key, ""))

    return PLACEHOLDER_PATTERN.sub(replacer, template_text)


def render_template_by_id(
    session: Session,
    company_id: int,
    template_id: int,
    lead_id: int | None = None,
    quote_id: int | None = None,
    product_id: int | None = None,
) -> dict:
    template = session.exec(
        select(MessageTemplate).where(
            MessageTemplate.id == template_id,
            MessageTemplate.company_id == company_id,
            MessageTemplate.is_active == True,
        )
    ).first()
    if not template:
        raise ValueError("Template not found")

    context = build_template_context(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        quote_id=quote_id,
        product_id=product_id,
    )

    rendered_subject = render_text(template.subject_template or "", context)
    rendered_body = render_text(template.body_template, context)

    return {
        "template_id": template.id,
        "channel": template.channel,
        "subject": rendered_subject,
        "body": rendered_body,
        "context": context,
    }
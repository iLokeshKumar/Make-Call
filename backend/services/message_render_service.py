from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select

from models.models import Campaign, Company, Lead, MessageTemplate, Product, Quote, User

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-zA-Z0-9_]+)\s*}}")

try:
    from jinja2.sandbox import SandboxedEnvironment as _SandboxedEnvironment

    _jinja_env = _SandboxedEnvironment(autoescape=False)
    _JINJA_AVAILABLE = True
except ImportError:
    _jinja_env = None
    _JINJA_AVAILABLE = False


def build_template_context(
    session: Session,
    company_id: int,
    lead_id: Optional[int] = None,
    quote_id: Optional[int] = None,
    product_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
    extra_context: Optional[dict] = None,
) -> dict:
    context: dict = {}

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
            context["lead_job_title"] = lead.job_title or ""
            context["lead_company"] = lead.company_name or ""
            # Flatten custom_fields as lead_<key>
            for k, v in (lead.custom_fields or {}).items():
                context[f"lead_{k}"] = str(v)

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

    if actor_user_id:
        user = session.get(User, actor_user_id)
        if user:
            context["agent_name"] = user.name or ""
            context["agent_email"] = user.email or ""

    if campaign_id:
        campaign = session.get(Campaign, campaign_id)
        if campaign:
            context["campaign_name"] = campaign.name or ""

    now = datetime.now()
    context["today"] = now.strftime("%B %d, %Y")
    context["day_of_week"] = now.strftime("%A")
    context["current_year"] = str(now.year)

    if extra_context:
        context.update(extra_context)

    return context


def render_text(template_text: str, context: dict) -> str:
    if _JINJA_AVAILABLE:
        try:
            return _jinja_env.from_string(template_text).render(**context)
        except Exception:
            pass
    # Fallback: simple {{variable}} substitution
    def replacer(match: re.Match) -> str:
        key = match.group(1)
        return str(context.get(key, ""))
    return PLACEHOLDER_PATTERN.sub(replacer, template_text)


def render_template_by_id(
    session: Session,
    company_id: int,
    template_id: int,
    lead_id: Optional[int] = None,
    quote_id: Optional[int] = None,
    product_id: Optional[int] = None,
    actor_user_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
    extra_context: Optional[dict] = None,
    ab_variant: str = "A",
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
        actor_user_id=actor_user_id,
        campaign_id=campaign_id,
        extra_context=extra_context,
    )

    subject_tmpl = (
        template.subject_template_b
        if ab_variant == "B" and template.subject_template_b
        else (template.subject_template or "")
    )
    rendered_subject = render_text(subject_tmpl, context)
    rendered_body = render_text(template.body_template, context)

    return {
        "template_id": template.id,
        "channel": template.channel,
        "subject": rendered_subject,
        "body": rendered_body,
        "context": context,
        "ab_variant": ab_variant,
    }

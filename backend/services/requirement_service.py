from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Lead, LeadRequirement, LeadRequirementUpsert, utc_now


def get_lead_or_404(session: Session, company_id: int, lead_id: int) -> Lead:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def get_latest_requirements(
    session: Session,
    company_id: int,
    lead_id: int,
) -> LeadRequirement | None:
    get_lead_or_404(session, company_id, lead_id)

    return session.exec(
        select(LeadRequirement).where(
            LeadRequirement.company_id == company_id,
            LeadRequirement.lead_id == lead_id,
        ).order_by(LeadRequirement.created_at.desc())
    ).first()


def update_lead_from_requirements(
    session: Session,
    lead: Lead,
    structured_data: dict | None,
) -> None:
    if not structured_data:
        return

    if structured_data.get("industry"):
        lead.industry = structured_data["industry"]

    if structured_data.get("website"):
        lead.website = structured_data["website"]

    if structured_data.get("city"):
        lead.city = structured_data["city"]

    if structured_data.get("state"):
        lead.state = structured_data["state"]

    if structured_data.get("country"):
        lead.country = structured_data["country"]

    if structured_data.get("qualification_status"):
        lead.qualification_status = structured_data["qualification_status"]

    if structured_data.get("next_action"):
        lead.next_action = structured_data["next_action"]

    if structured_data.get("budget_range"):
        lead.budget_range = structured_data["budget_range"]

    if structured_data.get("timeline"):
        lead.timeline = structured_data["timeline"]

    if structured_data.get("decision_maker"):
        lead.decision_maker = structured_data["decision_maker"]

    if structured_data.get("required_products"):
        lead.product_interest = structured_data["required_products"]

    lead.updated_at = utc_now()


def upsert_lead_requirements(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: LeadRequirementUpsert,
) -> LeadRequirement:
    lead = get_lead_or_404(session, company_id, data.lead_id)

    existing = session.exec(
        select(LeadRequirement).where(
            LeadRequirement.company_id == company_id,
            LeadRequirement.lead_id == data.lead_id,
        ).order_by(LeadRequirement.created_at.desc())
    ).first()

    if existing:
        if data.interaction_id is not None:
            existing.interaction_id = data.interaction_id
        if data.use_case is not None:
            existing.use_case = data.use_case
        if data.budget_range is not None:
            existing.budget_range = data.budget_range
        if data.timeline is not None:
            existing.timeline = data.timeline
        if data.decision_maker is not None:
            existing.decision_maker = data.decision_maker
        if data.competitors is not None:
            existing.competitors = data.competitors
        if data.pain_points is not None:
            existing.pain_points = data.pain_points
        if data.required_products is not None:
            existing.required_products = data.required_products
        if data.notes is not None:
            existing.notes = data.notes
        if data.structured_data is not None:
            existing.structured_data = data.structured_data

        existing.updated_at = utc_now()
        existing.updated_by = actor_user_id
        session.add(existing)

        update_lead_from_requirements(session, lead, existing.structured_data)
        lead.updated_by = actor_user_id
        session.add(lead)

        session.commit()
        session.refresh(existing)
        return existing

    requirement = LeadRequirement(
        company_id=company_id,
        lead_id=data.lead_id,
        interaction_id=data.interaction_id,
        use_case=data.use_case,
        budget_range=data.budget_range,
        timeline=data.timeline,
        decision_maker=data.decision_maker,
        competitors=data.competitors,
        pain_points=data.pain_points,
        required_products=data.required_products,
        notes=data.notes,
        structured_data=data.structured_data,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(requirement)

    update_lead_from_requirements(session, lead, data.structured_data)
    lead.updated_by = actor_user_id
    session.add(lead)

    session.commit()
    session.refresh(requirement)
    return requirement

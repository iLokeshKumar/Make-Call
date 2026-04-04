from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, SQLModel, func, select, delete

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import (
    Account,
    CallTask,
    CampaignRecipient,
    CompanySetting,
    CompanySettingsBulkUpsert,
    Interaction,
    LatencyLog,
    Lead,
    LeadCreate,
    LeadRequirement,
    LeadUpdate,
    OptOut,
    Outcome,
    Product,
    ProductCreate,
    ProductUpdate,
    Quote,
    User,
    utc_now,
)
from services.auth_service import user_has_any_permission
from services.demand_generation_service import trigger_new_lead_outreach, score_lead, enrich_lead_if_needed
from services.tracking_service import unsubscribe_lead
from utils.encryption import decrypt_value, encrypt_value


router = APIRouter(prefix="/crm", tags=["CRM"])


class AccountCreate(SQLModel):
    name: str
    industry: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    employee_count: Optional[int] = None
    notes: Optional[str] = None
    is_active: bool = True


class AccountUpdate(SQLModel):
    name: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    employee_count: Optional[int] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/accounts")
async def list_accounts(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    search: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(Account).where(Account.company_id == current_user.company_id)
    count_query = select(func.count()).select_from(Account).where(Account.company_id == current_user.company_id)

    if search:
        like = f"%{search}%"
        query = query.where(Account.name.ilike(like))
        count_query = count_query.where(Account.name.ilike(like))

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Account.name).offset((page - 1) * limit).limit(limit)
    ).all()
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.post("/accounts", response_model=Account)
async def create_account(
    data: AccountCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = Account(
        company_id=current_user.company_id,
        name=data.name.strip(),
        industry=data.industry,
        website=data.website,
        city=data.city,
        state=data.state,
        country=data.country,
        employee_count=data.employee_count,
        notes=data.notes,
        is_active=data.is_active,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.put("/accounts/{account_id}", response_model=Account)
async def update_account(
    account_id: int,
    data: AccountUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = session.exec(
        select(Account).where(Account.id == account_id, Account.company_id == current_user.company_id)
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(account, key, value)

    account.updated_at = utc_now()
    account.updated_by = current_user.id
    session.add(account)
    session.commit()
    session.refresh(account)
    return account


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    account = session.exec(
        select(Account).where(Account.id == account_id, Account.company_id == current_user.company_id)
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    session.delete(account)
    session.commit()
    return {"message": "Account deleted"}


class InteractionCreate(SQLModel):
    lead_id: int
    type: str
    content: Optional[str] = None
    transcript: Optional[str] = None
    direction: Optional[str] = None
    channel: Optional[str] = None


class InteractionListResponse(SQLModel):
    items: list[Interaction]
    total: int


@router.get("/interactions", response_model=InteractionListResponse)
async def list_interactions(
    lead_id: int | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(Interaction).where(Interaction.company_id == current_user.company_id)
    count_query = select(func.count()).select_from(Interaction).where(Interaction.company_id == current_user.company_id)

    if lead_id is not None:
        query = query.where(Interaction.lead_id == lead_id)
        count_query = count_query.where(Interaction.lead_id == lead_id)

    total = session.exec(count_query).one() or 0
    interactions = session.exec(
        query.order_by(Interaction.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()

    return InteractionListResponse(items=interactions, total=total)


@router.post("/interactions", response_model=Interaction)
async def create_interaction(
    data: InteractionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    interaction = Interaction(
        company_id=current_user.company_id,
        lead_id=data.lead_id,
        user_id=current_user.id,
        type=data.type,
        content=data.content,
        transcript=data.transcript,
        direction=data.direction,
        channel=data.channel,
        created_by=current_user.id,
        updated_by=current_user.id,
        status="logged",
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)
    return interaction

ALL_INTEGRATION_KEYS = {
    # Twilio + Messaging
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "PHONE_NUMBER_FROM",
    "WHATSAPP_NUMBER",
    "WHATSAPP_NUMBER_FROM",
    # Exotel / custom telephony
    "EXOTEL_ACCOUNT_SID",
    "EXOTEL_API_KEY",
    "EXOTEL_API_TOKEN",
    "EXOPHONE",
    "EXOTEL_APP_ID",
    # EnableX
    "ENABLEX_APP_ID",
    "ENABLEX_APP_KEY",
    "ENABLEX_FROM_NUMBER",
    # STT
    "DEEPGRAM_API_KEY",
    "SARVAM_API_KEY",
    "DEEPGRAM_STT_MODEL",
    "CARTESIA_STT_MODEL",
    "SARVAM_STT_MODEL",
    "ELEVENLABS_STT_MODEL",
    "DEEPGRAM_VOICE",
    "SARVAM_VOICE_ID",
    "SMALLEST_STT_MODEL",
    "SMALLEST_VOICE_ID",
    # TTS
    "CARTESIA_API_KEY",
    "ELEVENLABS_API_KEY",
    "MIMO_API_KEY",
    "CARTESIA_VOICE_ID",
    "ELEVENLABS_VOICE_ID",
    "MIMO_VOICE_ID",
    "SARVAM_VOICE_ID",
    "DEEPGRAM_TTS_MODEL",
    "ELEVENLABS_TTS_MODEL",
    "MIMO_TTS_MODEL",
    "SARVAM_TTS_MODEL",
    "CARTESIA_TTS_MODEL",
    "MISTRAL_TTS_MODEL",
    "SMALLEST_API_KEY",
    "SMALLEST_TTS_MODEL",
    # LLM
    "OPENAI_API_KEY",
    "MISTRAL_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "PERPLEXITY_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY",
    "MIMO_MODEL",
    "MISTRAL_MODEL",
    "OPENAI_MODEL",
    "GEMINI_MODEL",
    "ANTHROPIC_MODEL",
    "PERPLEXITY_MODEL",
    "OPENROUTER_MODEL",
    "CEREBRAS_MODEL",
    "MIMO_MODEL",
    # Email / SMTP
    "SMTP_SERVER",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
    # Enrichment
    "APOLLO_API_KEY",
}

SECRET_INTEGRATION_KEYS = {
    "TWILIO_AUTH_TOKEN",
    "EXOTEL_API_KEY",
    "EXOTEL_API_TOKEN",
    "ENABLEX_APP_KEY",
    "DEEPGRAM_API_KEY",
    "SARVAM_API_KEY",
    "ELEVENLABS_API_KEY",
    "CARTESIA_API_KEY",
    "MIMO_API_KEY",
    "MISTRAL_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "PERPLEXITY_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "SMTP_PASSWORD",
    "SMTP_USERNAME",
    "SMALLEST_API_KEY",
    "APOLLO_API_KEY",
    "WHATSAPP_NUMBER",
    "WHATSAPP_NUMBER_FROM",
}

PLAIN_INTEGRATION_KEYS = ALL_INTEGRATION_KEYS - SECRET_INTEGRATION_KEYS


@router.post("/leads", response_model=Lead)
async def create_lead(
    data: LeadCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    owner_user_id = data.owner_user_id or current_user.id

    owner = session.exec(
        select(User).where(
            User.id == owner_user_id,
            User.company_id == current_user.company_id,
            User.is_active.is_(True),
        )
    ).first()
    if not owner:
        raise HTTPException(status_code=400, detail="Invalid lead owner")

    existing = session.exec(
        select(Lead).where(
            Lead.company_id == current_user.company_id,
            Lead.normalized_phone == data.normalized_phone.strip(),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Lead already exists for this company")

    lead = Lead(
        company_id=current_user.company_id,
        owner_user_id=owner_user_id,
        name=data.name.strip(),
        normalized_phone=data.normalized_phone.strip(),
        email=data.email.strip().lower() if data.email else None,
        status=data.status or "new",
        notes=data.notes,
        source="manual",
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(lead)
    session.commit()
    session.refresh(lead)
    try:
        trigger_new_lead_outreach(
            session=session,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            lead_id=lead.id,
        )
        session.refresh(lead)
    except Exception:
        # Lead creation should not fail if auto-trigger logic is unavailable or misconfigured.
        pass
    return lead


@router.get("/leads")
async def list_leads(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    owner_user_id: int | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_read_company = user_has_any_permission(session, current_user.id, {"lead.read_company"})
    can_read_own = user_has_any_permission(session, current_user.id, {"lead.read_own"})

    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(Lead.company_id == current_user.company_id)
    count_query = select(func.count()).select_from(Lead).where(Lead.company_id == current_user.company_id)

    if can_read_company:
        if owner_user_id is not None:
            query = query.where(Lead.owner_user_id == owner_user_id)
            count_query = count_query.where(Lead.owner_user_id == owner_user_id)
    else:
        query = query.where(Lead.owner_user_id == current_user.id)
        count_query = count_query.where(Lead.owner_user_id == current_user.id)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Lead.created_at.desc()).offset((page - 1) * limit).limit(limit)
    ).all()

    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/leads/{lead_id}", response_model=Lead)
async def get_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_read_company = user_has_any_permission(session, current_user.id, {"lead.read_company"})
    can_read_own = user_has_any_permission(session, current_user.id, {"lead.read_own"})

    if not can_read_company and not can_read_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_read_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    return lead


@router.put("/leads/{lead_id}", response_model=Lead)
async def update_lead(
    lead_id: int,
    data: LeadUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    payload = data.model_dump(exclude_unset=True)

    if "owner_user_id" in payload and payload["owner_user_id"] is not None:
        owner = session.exec(
            select(User).where(
                User.id == payload["owner_user_id"],
                User.company_id == current_user.company_id,
                User.is_active.is_(True),
            )
        ).first()
        if not owner:
            raise HTTPException(status_code=400, detail="Invalid lead owner")

    if "normalized_phone" in payload and payload["normalized_phone"] != lead.normalized_phone:
        duplicate = session.exec(
            select(Lead).where(
                Lead.company_id == current_user.company_id,
                Lead.normalized_phone == payload["normalized_phone"],
                Lead.id != lead.id,
            )
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Phone already used in this company")

    for key, value in payload.items():
        setattr(lead, key, value)

    lead.updated_at = utc_now()
    lead.updated_by = current_user.id
    session.add(lead)
    session.commit()
    session.refresh(lead)
    return lead


@router.delete("/leads/{lead_id}")
async def delete_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    can_delete_company = user_has_any_permission(session, current_user.id, {"lead.delete_company"})
    can_delete_own = user_has_any_permission(session, current_user.id, {"lead.delete_own"})

    if not can_delete_company and not can_delete_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_delete_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Delete related records first to avoid foreign key constraint violations
    # Delete in order of dependencies (most dependent first)

    # Delete latency logs associated with this lead
    session.exec(delete(LatencyLog).where(LatencyLog.lead_id == lead_id))

    # Delete opt-outs associated with this lead
    session.exec(delete(OptOut).where(OptOut.lead_id == lead_id))

    # Delete outcomes associated with this lead
    session.exec(delete(Outcome).where(Outcome.lead_id == lead_id))

    # Delete lead requirements associated with this lead
    session.exec(delete(LeadRequirement).where(LeadRequirement.lead_id == lead_id))

    # Delete quotes associated with this lead
    session.exec(delete(Quote).where(Quote.lead_id == lead_id))

    # Delete call tasks associated with this lead (before campaign recipients)
    session.exec(delete(CallTask).where(CallTask.lead_id == lead_id))

    # Delete campaign recipients associated with this lead
    session.exec(delete(CampaignRecipient).where(CampaignRecipient.lead_id == lead_id))

    # Delete interactions associated with this lead (last, as other tables may reference them)
    interaction_ids = [row for row in session.exec(select(Interaction.id).where(Interaction.lead_id == lead_id)).all()]
    if interaction_ids:
        session.exec(delete(LatencyLog).where(LatencyLog.interaction_id.in_(interaction_ids)))
        session.exec(delete(Interaction).where(Interaction.lead_id == lead_id))

    # Delete the lead
    session.delete(lead)
    session.commit()
    return {"message": "Lead deleted"}


@router.get("/ai-insights")
async def ai_insights(
    lead_id: int = Query(default=None, ge=1),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not lead_id:
        raise HTTPException(status_code=400, detail="lead_id is required")

    lead = session.get(Lead, lead_id)
    if not lead or lead.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Lead not found")

    interactions = session.exec(
        select(Interaction)
        .where(
            Interaction.company_id == current_user.company_id,
            Interaction.lead_id == lead_id,
        )
        .order_by(Interaction.created_at.desc())
    ).all()

    manual_notes = [i for i in interactions if (i.type or "").lower() == "note"]
    call_interactions = [i for i in interactions if (i.type or "").lower().startswith("call")]
    completed_calls = [i for i in call_interactions if (i.status or "").lower() == "completed"]

    summary_parts = [
        f"{lead.name} is currently in the \"{lead.status}\" stage.",
        f"{len(interactions)} interactions have been logged.",
    ]

    if manual_notes:
        summary_parts.append(f"{len(manual_notes)} manual notes capture your latest context.")

    if call_interactions:
        summary_parts.append(f"{len(completed_calls)} of {len(call_interactions)} calls have been completed.")
    elif lead.next_action:
        summary_parts.append(f"Next action: {lead.next_action}.")

    if lead.next_action_due_at:
        summary_parts.append(f"Due by {lead.next_action_due_at}.")

    return {"summary": " ".join(summary_parts)}


@router.post("/products", response_model=Product)
async def create_product(
    data: ProductCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    sku = data.sku.strip() if data.sku else None
    if sku:
        existing = session.exec(
            select(Product).where(
                Product.company_id == current_user.company_id,
                Product.sku == sku,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="SKU already exists in this company")

    product = Product(
        company_id=current_user.company_id,
        name=data.name.strip(),
        sku=sku,
        stock=data.stock,
        price=data.price,
        currency=data.currency,
        note=data.note,
        is_active=data.is_active,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.get("/products")
async def list_products(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    is_active: bool | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.read")),
):
    query = select(Product).where(Product.company_id == current_user.company_id)
    count_query = select(func.count()).select_from(Product).where(Product.company_id == current_user.company_id)

    if is_active is not None:
        query = query.where(Product.is_active == is_active)
        count_query = count_query.where(Product.is_active == is_active)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Product.created_at.desc()).offset((page - 1) * limit).limit(limit)
    ).all()
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/products/{product_id}", response_model=Product)
async def get_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.read")),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == current_user.company_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == current_user.company_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    payload = data.model_dump(exclude_unset=True)
    if "sku" in payload:
        payload["sku"] = payload["sku"].strip() if payload["sku"] else None
        if payload["sku"] and payload["sku"] != product.sku:
            duplicate = session.exec(
                select(Product).where(
                    Product.company_id == current_user.company_id,
                    Product.sku == payload["sku"],
                    Product.id != product.id,
                )
            ).first()
            if duplicate:
                raise HTTPException(status_code=400, detail="SKU already exists in this company")

    if "name" in payload and payload["name"] is not None:
        payload["name"] = payload["name"].strip()

    for key, value in payload.items():
        setattr(product, key, value)

    product.updated_at = utc_now()
    product.updated_by = current_user.id
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == current_user.company_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    session.delete(product)
    session.commit()
    return {"message": "Product deleted"}


@router.get("/inventory")
async def list_inventory(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.read")),
):
    return await list_products(page=page, limit=limit, is_active=None, session=session, current_user=current_user)


@router.post("/inventory", response_model=Product)
async def create_inventory_product(
    data: ProductCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    return await create_product(data=data, session=session, current_user=current_user)


@router.delete("/inventory/{product_id}")
async def delete_inventory_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    return await delete_product(product_id=product_id, session=session, current_user=current_user)


@router.put("/inventory/{product_id}", response_model=Product)
async def update_inventory_product(
    product_id: int,
    data: ProductUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    return await update_product(
        product_id=product_id,
        data=data,
        session=session,
        current_user=current_user,
    )


@router.get("/company-settings")
async def get_company_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    settings = session.exec(
        select(CompanySetting).where(CompanySetting.company_id == current_user.company_id)
    ).all()
    return {item.key: "***MASKED***" if item.is_secret else item.value for item in settings}


@router.patch("/company-settings")
async def upsert_company_settings(
    payload: CompanySettingsBulkUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    for item in payload.items:
        existing = session.exec(
            select(CompanySetting).where(
                CompanySetting.company_id == current_user.company_id,
                CompanySetting.key == item.key,
            )
        ).first()

        stored_value = encrypt_value(item.value) if item.is_secret else item.value
        if existing:
            existing.value = stored_value
            existing.is_secret = item.is_secret
            existing.updated_at = utc_now()
            existing.updated_by = current_user.id
            session.add(existing)
        else:
            session.add(
                CompanySetting(
                    company_id=current_user.company_id,
                    key=item.key,
                    value=stored_value,
                    is_secret=item.is_secret,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
            )

    session.commit()
    return {"message": "Company settings updated"}


@router.get("/company-integrations")
async def get_company_integrations(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("integrations.read_company")),
):
    settings = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == current_user.company_id,
            CompanySetting.key.in_(ALL_INTEGRATION_KEYS | {"SMTP_HOST"}),
        )
    ).all()

    result: dict[str, str] = {}
    for item in settings:
        result_key = "SMTP_SERVER" if item.key == "SMTP_HOST" else item.key

        if item.is_secret:
            raw = decrypt_value(item.value)
            if raw and len(raw) > 8:
                result[result_key] = raw[:3] + "..." + raw[-4:]
            else:
                result[result_key] = "***" if raw else ""
        else:
            result[result_key] = item.value

    if "SMTP_HOST" in result and "SMTP_SERVER" not in result:
        result["SMTP_SERVER"] = result["SMTP_HOST"]

    return result


@router.patch("/company-integrations")
async def update_company_integrations(
    payload: CompanySettingsBulkUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("integrations.manage_company")),
):
    allowed_keys = SECRET_INTEGRATION_KEYS | PLAIN_INTEGRATION_KEYS | {"SMTP_HOST", "SMTP_SERVER"}

    for item in payload.items:
        if item.key not in allowed_keys:
            continue

        normalized_key = "SMTP_HOST" if item.key == "SMTP_SERVER" else item.key
        value = item.value.strip()
        if not value or value == "***MASKED***" or "..." in value:
            continue

        is_secret = normalized_key in SECRET_INTEGRATION_KEYS
        stored_value = encrypt_value(value) if is_secret else value
        existing = session.exec(
            select(CompanySetting).where(
                CompanySetting.company_id == current_user.company_id,
                CompanySetting.key == normalized_key,
            )
        ).first()

        if existing:
            existing.value = stored_value
            existing.is_secret = is_secret
            existing.updated_at = utc_now()
            existing.updated_by = current_user.id
            session.add(existing)
        else:
            session.add(
                CompanySetting(
                    company_id=current_user.company_id,
                    key=normalized_key,
                    value=stored_value,
                    is_secret=is_secret,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
            )

    session.commit()
    return {"message": "Company integrations updated"}


@router.post("/leads/{lead_id}/enrich")
async def enrich_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Enrich a lead using the demand generation service."""
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    result = enrich_lead_if_needed(session, current_user.company_id, current_user.id, lead_id)
    return {"lead_id": lead_id, "enriched": result, "message": "Enrichment complete." if result else "No enrichment needed or no data found."}


@router.post("/leads/{lead_id}/rescore")
async def rescore_lead(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Rescore a lead using the demand generation service."""
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    # Enrich first, then score
    enrich_result = enrich_lead_if_needed(session, current_user.company_id, current_user.id, lead_id)
    score_result = score_lead(session, current_user.company_id, lead_id)
    
    return {
        "lead_id": lead_id,
        "enrichment": enrich_result,
        "scoring": score_result,
    }


@router.post("/leads/{lead_id}/opt-out")
async def opt_out_lead(
    lead_id: int,
    channel: str = Query(..., description="Channel to opt out from (email, whatsapp, call, sms)"),
    reason: str | None = Query(None, description="Optional reason for opt-out"),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.update")),
):
    """Opt out a lead from a specific communication channel."""
    can_update_company = user_has_any_permission(session, current_user.id, {"lead.update_company"})
    can_update_own = user_has_any_permission(session, current_user.id, {"lead.update_own"})

    if not can_update_company and not can_update_own:
        raise HTTPException(status_code=403, detail="Permission denied")

    query = select(Lead).where(
        Lead.id == lead_id,
        Lead.company_id == current_user.company_id,
    )
    if not can_update_company:
        query = query.where(Lead.owner_user_id == current_user.id)

    lead = session.exec(query).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    if channel not in {"email", "whatsapp", "call", "sms"}:
        raise HTTPException(status_code=400, detail="Invalid channel. Must be one of: email, whatsapp, call, sms")

    opt_out = unsubscribe_lead(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=lead_id,
        channel=channel,
        reason=reason,
    )
    
    return {
        "lead_id": lead_id,
        "channel": channel,
        "opted_out": True,
        "reason": reason,
    }

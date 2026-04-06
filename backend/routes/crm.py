from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlmodel import Session, SQLModel, func, select, delete

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import (
    Account,
    CallCoachScore,
    CallTask,
    CampaignRecipient,
    CompanySetting,
    CompanySettingsBulkUpsert,
    CompetitorMention,
    EngagementEvent,
    Interaction,
    LatencyLog,
    Lead,
    LeadCreate,
    LeadRequirement,
    LeadUpdate,
    ObjectionEntry,
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
    limit: int = Query(default=20, ge=1, le=1000),
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
    limit: int = Query(default=20, ge=1, le=1000),
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
    # Email / IMAP (inbound polling)
    "IMAP_SERVER",
    "IMAP_PORT",
    "IMAP_USERNAME",
    "IMAP_PASSWORD",
    # Enrichment
    "APOLLO_API_KEY",
    "LUSHA_API_KEY",
    "ZOOMINFO_CLIENT_ID",
    "ZOOMINFO_API_KEY",
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
    "IMAP_PASSWORD",
    "IMAP_USERNAME",
    "SMALLEST_API_KEY",
    "APOLLO_API_KEY",
    "LUSHA_API_KEY",
    "ZOOMINFO_CLIENT_ID",
    "ZOOMINFO_API_KEY",
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


# ---------------------------------------------------------------------------
# Lead import endpoints
# ---------------------------------------------------------------------------

@router.get("/leads/import/template")
async def download_import_template():
    """Return a CSV template for manual bulk upload. No auth required — static file."""
    from fastapi.responses import Response
    headers_row = "name,normalized_phone,email,company_name,job_title,industry,city,state,country,notes\n"
    sample = "John Smith,+919876543210,john@example.com,Acme Corp,VP Sales,SaaS,Mumbai,Maharashtra,India,\n"
    return Response(
        content=headers_row + sample,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_template.csv"},
    )


@router.post("/leads/import/file")
async def import_leads_from_file(
    file: UploadFile = File(...),
    source_tag: str = Form(default="csv_import"),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Upload a CSV or Excel file to bulk-import leads."""
    from services.lead_import_service import bulk_create_leads, parse_file_upload
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    allowed = {".csv", ".xlsx", ".xls"}
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")

    try:
        lead_dicts = parse_file_upload(content, file.filename, source_tag)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")

    if not lead_dicts:
        raise HTTPException(status_code=422, detail="No valid rows found in file. Check column headers.")

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result


class ApolloImportRequest(SQLModel):
    job_titles: list[str] = []
    locations: list[str] = []
    companies: list[str] = []
    keywords: str = ""
    limit: int = 25


@router.post("/leads/import/apollo")
async def import_leads_from_apollo(
    body: ApolloImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Search Apollo.io and import matching contacts as leads."""
    from credentials_service import get_company_credential
    from services.lead_import_service import bulk_create_leads, search_apollo_leads
    api_key = get_company_credential(session, current_user.company_id, "APOLLO_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Apollo API key not configured. Add it in Settings → Integrations.")

    try:
        lead_dicts = search_apollo_leads(
            api_key=api_key,
            job_titles=body.job_titles or None,
            locations=body.locations or None,
            companies=body.companies or None,
            keywords=body.keywords or None,
            limit=min(body.limit, 100),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not lead_dicts:
        return {"imported": 0, "skipped": 0, "errors": [], "message": "Apollo returned no results for these filters."}

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result


class LushaQuery(SQLModel):
    first_name: str
    last_name: str = ""
    company: str = ""


class LushaImportRequest(SQLModel):
    queries: list[LushaQuery]


@router.post("/leads/import/lusha")
async def import_leads_from_lusha(
    body: LushaImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Lookup contacts on Lusha and import as leads."""
    from credentials_service import get_company_credential
    from services.lead_import_service import bulk_create_leads, search_lusha_leads
    api_key = get_company_credential(session, current_user.company_id, "LUSHA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Lusha API key not configured. Add it in Settings → Integrations.")

    if not body.queries:
        raise HTTPException(status_code=400, detail="Provide at least one name/company query")

    try:
        lead_dicts = search_lusha_leads(
            api_key=api_key,
            queries=[q.dict() for q in body.queries],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lusha API error: {exc}")

    if not lead_dicts:
        return {"imported": 0, "skipped": 0, "errors": [], "message": "Lusha returned no results."}

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result


class ZoomInfoImportRequest(SQLModel):
    job_titles: list[str] = []
    locations: list[str] = []
    companies: list[str] = []
    departments: list[str] = []
    keywords: str = ""
    limit: int = 25


@router.post("/leads/import/zoominfo")
async def import_leads_from_zoominfo(
    body: ZoomInfoImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Search ZoomInfo and import matching contacts as leads."""
    from credentials_service import get_company_credential
    from services.lead_import_service import bulk_create_leads, search_zoominfo_leads

    client_id = get_company_credential(session, current_user.company_id, "ZOOMINFO_CLIENT_ID")
    private_key = get_company_credential(session, current_user.company_id, "ZOOMINFO_API_KEY")
    if not client_id or not private_key:
        raise HTTPException(
            status_code=400,
            detail="ZoomInfo credentials not configured. Add ZOOMINFO_CLIENT_ID and ZOOMINFO_API_KEY in Settings → Integrations.",
        )

    try:
        lead_dicts = search_zoominfo_leads(
            client_id=client_id,
            private_key=private_key,
            job_titles=body.job_titles or None,
            locations=body.locations or None,
            companies=body.companies or None,
            departments=body.departments or None,
            keywords=body.keywords or None,
            limit=min(body.limit, 100),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not lead_dicts:
        return {"imported": 0, "skipped": 0, "errors": [], "message": "ZoomInfo returned no results for these filters."}

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result


@router.get("/leads")
async def list_leads(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=1000),
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


@router.patch("/leads/{lead_id}", response_model=Lead)
async def patch_lead(
    lead_id: int,
    data: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Partial update — accepts any subset of Lead fields (e.g., ism_stage, preferred_language)."""
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

    # Only allow known Lead fields
    allowed = {c.key for c in Lead.__table__.columns} - {"id", "company_id", "created_at", "created_by"}
    for key, value in data.items():
        if key in allowed:
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
    limit: int = Query(default=20, ge=1, le=1000),
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
    limit: int = Query(default=20, ge=1, le=1000),
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


@router.get("/leads/{lead_id}/enrichment-trace")
async def get_enrichment_trace(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return the waterfall enrichment trace for a lead:
    DB → Apollo → Lusha → Validation
    Each step shows its status, fields contributed, and whether credentials are configured.
    """
    from credentials_service import get_company_credential

    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    def _has(val) -> bool:
        return bool(val and str(val).strip())

    # ── Step 1: DB (what we already have) ─────────────────────────────────
    db_fields = {
        "name": _has(lead.name),
        "email": _has(lead.email),
        "phone": _has(lead.normalized_phone),
        "website": _has(lead.website),
        "city": _has(lead.city),
        "industry": _has(lead.industry),
        "company_name": _has(lead.company_name),
        "designation": _has(lead.designation),
    }
    db_populated = [k for k, v in db_fields.items() if v]
    db_missing = [k for k, v in db_fields.items() if not v]

    # ── Step 2: Apollo ─────────────────────────────────────────────────────
    apollo_key = get_company_credential(session, current_user.company_id, "APOLLO_API_KEY")
    apollo_configured = bool(apollo_key)
    apollo_used = (lead.source or "").lower() in {"apollo api", "apollo"}
    apollo_status = "enriched" if apollo_used else ("available" if apollo_configured else "not_configured")

    # ── Step 3: Lusha ──────────────────────────────────────────────────────
    lusha_key = get_company_credential(session, current_user.company_id, "LUSHA_API_KEY")
    lusha_configured = bool(lusha_key)
    lusha_status = "available" if lusha_configured else "not_configured"

    # ── Step 4: Validation ─────────────────────────────────────────────────
    email_valid = _has(lead.email) and "@" in lead.email and "." in lead.email.split("@")[-1]
    phone_valid = _has(lead.normalized_phone) and lead.normalized_phone.startswith("+")
    validation_status = "passed" if (email_valid or phone_valid) else "partial"

    return {
        "lead_id": lead_id,
        "enrichment_status": lead.enrichment_status,
        "last_enriched_at": lead.last_enriched_at.isoformat() if lead.last_enriched_at else None,
        "steps": [
            {
                "name": "Database",
                "key": "db",
                "status": "enriched" if len(db_populated) >= 4 else ("partial" if db_populated else "empty"),
                "populated_fields": db_populated,
                "missing_fields": db_missing,
                "description": f"{len(db_populated)}/{len(db_fields)} fields populated from CRM data",
            },
            {
                "name": "Apollo.io",
                "key": "apollo",
                "status": apollo_status,
                "configured": apollo_configured,
                "description": "B2B contact & company enrichment via Apollo API",
            },
            {
                "name": "Lusha",
                "key": "lusha",
                "status": lusha_status,
                "configured": lusha_configured,
                "description": "Direct-dial phone & verified email via Lusha API",
            },
            {
                "name": "Validation",
                "key": "validation",
                "status": validation_status,
                "email_valid": email_valid,
                "phone_valid": phone_valid,
                "description": "Email format check + E.164 phone number validation",
            },
        ],
    }


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


# ── Objection Library ─────────────────────────────────────────────────────────

class ObjectionCreate(SQLModel):
    objection_key: str
    objection_text: str
    category: str = "general"
    rebuttal: Optional[str] = None
    is_active: bool = True


class ObjectionUpdate(SQLModel):
    objection_text: Optional[str] = None
    category: Optional[str] = None
    rebuttal: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/objections")
async def list_objections(
    category: Optional[str] = Query(None),
    is_active: Optional[bool] = Query(None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    query = select(ObjectionEntry).where(
        ObjectionEntry.company_id == current_user.company_id
    )
    count_query = select(func.count()).select_from(ObjectionEntry).where(
        ObjectionEntry.company_id == current_user.company_id
    )
    if category:
        query = query.where(ObjectionEntry.category == category)
        count_query = count_query.where(ObjectionEntry.category == category)
    if is_active is not None:
        query = query.where(ObjectionEntry.is_active == is_active)
        count_query = count_query.where(ObjectionEntry.is_active == is_active)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(ObjectionEntry.frequency_count.desc())
             .offset((page - 1) * limit)
             .limit(limit)
    ).all()
    return {"total": total, "page": page, "items": items}


@router.post("/objections")
async def create_objection(
    data: ObjectionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    key = data.objection_key.strip().lower()
    existing = session.exec(
        select(ObjectionEntry).where(
            ObjectionEntry.company_id == current_user.company_id,
            ObjectionEntry.objection_key == key,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Objection key already exists for this company")

    entry = ObjectionEntry(
        company_id=current_user.company_id,
        objection_key=key,
        objection_text=data.objection_text.strip(),
        category=data.category,
        rebuttal=data.rebuttal,
        is_active=data.is_active,
        frequency_count=0,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.patch("/objections/{objection_id}")
async def update_objection(
    objection_id: int,
    data: ObjectionUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    entry = session.exec(
        select(ObjectionEntry).where(
            ObjectionEntry.id == objection_id,
            ObjectionEntry.company_id == current_user.company_id,
        )
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Objection not found")

    if data.objection_text is not None:
        entry.objection_text = data.objection_text.strip()
    if data.category is not None:
        entry.category = data.category
    if data.rebuttal is not None:
        entry.rebuttal = data.rebuttal
    if data.is_active is not None:
        entry.is_active = data.is_active

    entry.updated_at = utc_now()
    entry.updated_by = current_user.id
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.delete("/objections/{objection_id}", status_code=204)
async def delete_objection(
    objection_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    entry = session.exec(
        select(ObjectionEntry).where(
            ObjectionEntry.id == objection_id,
            ObjectionEntry.company_id == current_user.company_id,
        )
    ).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Objection not found")
    session.delete(entry)
    session.commit()


# ── WhatsApp Thread ───────────────────────────────────────────────────────────

class WhatsAppSendRequest(SQLModel):
    message: str


@router.get("/leads/{lead_id}/whatsapp")
async def get_whatsapp_thread(
    lead_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all WhatsApp interactions for a lead, ordered chronologically."""
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    query = (
        select(Interaction)
        .where(
            Interaction.company_id == current_user.company_id,
            Interaction.lead_id == lead_id,
            Interaction.channel == "whatsapp",
        )
        .order_by(Interaction.created_at.asc())
    )
    total = session.exec(
        select(func.count()).select_from(Interaction).where(
            Interaction.company_id == current_user.company_id,
            Interaction.lead_id == lead_id,
            Interaction.channel == "whatsapp",
        )
    ).one()
    messages = session.exec(query.offset((page - 1) * limit).limit(limit)).all()
    return {"total": total, "lead_name": lead.name, "items": messages}


@router.post("/leads/{lead_id}/whatsapp/send")
async def send_whatsapp_to_lead_route(
    lead_id: int,
    data: WhatsAppSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Send a WhatsApp message to a lead.
    Routes to the configured telephony provider: Twilio, Exotel (or Twilio fallback for EnableX).
    Logs the interaction regardless of delivery outcome.
    """
    from services.communication_service import send_whatsapp_to_lead as _send_wa
    result = _send_wa(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=lead_id,
        body=data.message,
    )
    return result


# ── Email Thread ──────────────────────────────────────────────────────────────

class EmailSendRequest(SQLModel):
    subject: str
    body: str


@router.get("/leads/{lead_id}/email")
async def get_email_thread(
    lead_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all email interactions for a lead, ordered chronologically."""
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    _email_filter = [
        Interaction.company_id == current_user.company_id,
        Interaction.lead_id == lead_id,
        Interaction.channel == "email",
        Interaction.status != "dismissed",
    ]
    query = (
        select(Interaction)
        .where(*_email_filter)
        .order_by(Interaction.created_at.asc())
    )
    total = session.exec(
        select(func.count()).select_from(Interaction).where(*_email_filter)
    ).one()
    emails = session.exec(query.offset((page - 1) * limit).limit(limit)).all()

    # Attach open/click engagement events to each email interaction
    interaction_ids = [e.id for e in emails]
    events_by_interaction: dict[int, list[dict]] = {}
    if interaction_ids:
        engagement_rows = session.exec(
            select(EngagementEvent)
            .where(
                EngagementEvent.interaction_id.in_(interaction_ids),
                EngagementEvent.event_type.in_(["open", "click", "reply"]),
            )
            .order_by(EngagementEvent.created_at.asc())
        ).all()
        for ev in engagement_rows:
            events_by_interaction.setdefault(ev.interaction_id, []).append({
                "event_type": ev.event_type,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                "payload": ev.payload or {},
            })

    items = []
    for email in emails:
        d = email.dict()
        d["events"] = events_by_interaction.get(email.id, [])
        items.append(d)

    return {"total": total, "lead_email": lead.email, "items": items}


@router.delete("/leads/{lead_id}/email/{interaction_id}")
async def dismiss_email_from_thread(
    lead_id: int,
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Soft-remove an email interaction from the thread (sets status='dismissed')."""
    interaction = session.exec(
        select(Interaction).where(
            Interaction.id == interaction_id,
            Interaction.lead_id == lead_id,
            Interaction.company_id == current_user.company_id,
            Interaction.channel == "email",
        )
    ).first()
    if not interaction:
        raise HTTPException(status_code=404, detail="Email not found")
    interaction.status = "dismissed"
    interaction.updated_by = current_user.id
    session.add(interaction)
    session.commit()
    return {"status": "dismissed"}


@router.post("/leads/{lead_id}/email/send")
async def send_email_to_lead_route(
    lead_id: int,
    data: EmailSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Send an email to a lead and log it as an interaction."""
    from services.communication_service import send_email_to_lead as _send_email
    result = _send_email(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=lead_id,
        subject=data.subject,
        body=data.body,
    )
    return result


_USER_PERSONAL_KEYS = {"SYSTEM_PROMPT", "AI_VERBOSITY"}

@router.get("/me/settings")
async def get_my_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the calling user's personal AI/preference settings. Accessible to all roles."""
    from credentials_service import get_user_setting_value
    return {key: get_user_setting_value(session, current_user.id, key) or "" for key in _USER_PERSONAL_KEYS}


@router.put("/me/settings")
async def save_my_settings(
    data: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Save the calling user's personal AI/preference settings. Accessible to all roles."""
    from credentials_service import save_user_setting
    for key, value in data.items():
        if key in _USER_PERSONAL_KEYS and isinstance(value, str):
            save_user_setting(session, current_user.id, key, value)
    session.commit()
    return {"status": "saved"}


_USER_EMAIL_KEYS = [
    "SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL",
    "IMAP_SERVER", "IMAP_PORT", "IMAP_USERNAME", "IMAP_PASSWORD",
]
_USER_EMAIL_SECRET_KEYS = {"SMTP_PASSWORD", "IMAP_PASSWORD", "SMTP_USERNAME", "IMAP_USERNAME"}


@router.get("/me/email-settings")
async def get_my_email_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the calling user's personal email settings. Accessible to all roles."""
    from credentials_service import get_user_setting_value
    result: dict[str, str] = {}
    for key in _USER_EMAIL_KEYS:
        val = get_user_setting_value(session, current_user.id, key) or ""
        if val and key in _USER_EMAIL_SECRET_KEYS:
            result[key] = "***" + val[-4:] if len(val) > 4 else "***"
        else:
            result[key] = val
    return result


@router.put("/me/email-settings")
async def save_my_email_settings(
    data: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Save the calling user's personal email settings. Accessible to all roles."""
    from credentials_service import save_user_setting
    for key, value in data.items():
        if key in _USER_EMAIL_KEYS and isinstance(value, str) and value and not value.startswith("***"):
            save_user_setting(session, current_user.id, key, value)
    session.commit()
    return {"status": "saved"}


@router.post("/email/sync")
async def trigger_imap_sync(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Trigger an immediate IMAP inbox poll for the current company."""
    from services.imap_poller_service import trigger_imap_poll
    result = await trigger_imap_poll(current_user.company_id, user_id=current_user.id)
    return result


# ── Competitor Mentions ───────────────────────────────────────────────────────

class CounterScriptUpsert(SQLModel):
    competitor_name: str
    counter_script: str


@router.get("/competitors/summary")
async def get_competitor_summary_route(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return aggregated mention counts per competitor for the company."""
    from services.competitor_service import get_competitor_summary
    return get_competitor_summary(session, current_user.company_id)


@router.get("/leads/{lead_id}/competitors")
async def get_lead_competitor_mentions(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return all competitor mentions detected on calls with this lead."""
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    from services.competitor_service import get_competitor_mentions_for_lead
    mentions = get_competitor_mentions_for_lead(session, current_user.company_id, lead_id)
    return {"lead_id": lead_id, "lead_name": lead.name, "items": mentions}


@router.post("/competitors/counter-script")
async def upsert_counter_script_route(
    data: CounterScriptUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage")),
):
    """Store or update the counter-script for a competitor."""
    from services.competitor_service import upsert_counter_script
    return upsert_counter_script(
        session=session,
        company_id=current_user.company_id,
        competitor_name=data.competitor_name,
        counter_script=data.counter_script,
        actor_user_id=current_user.id,
    )


# ── AI Sales Coach ────────────────────────────────────────────────────────────

@router.get("/coach/scores")
async def list_coach_scores(
    limit: int = Query(default=20, ge=1, le=1000),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the most recent AI coach scores for the company."""
    from services.call_coach_service import get_recent_coach_scores
    scores = get_recent_coach_scores(session, current_user.company_id, limit)
    return {"items": scores}


@router.get("/coach/averages")
async def get_coach_averages_route(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return aggregate performance averages across all scored calls."""
    from services.call_coach_service import get_coach_averages
    return get_coach_averages(session, current_user.company_id)


@router.get("/coach/scores/{interaction_id}")
async def get_coach_score_for_interaction_route(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    from services.call_coach_service import get_coach_score_for_interaction
    score = get_coach_score_for_interaction(session, current_user.company_id, interaction_id)
    return score  # None serialises as JSON null — frontend checks for null


# ── Predictive Dialer ─────────────────────────────────────────────────────────

@router.get("/leads/{lead_id}/best-call-times")
async def get_best_call_times(
    lead_id: int,
    n_windows: int = Query(default=5, ge=1, le=20),
    lookahead_hours: int = Query(default=72, ge=12, le=168),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return the top N predicted call windows for this lead, ranked by connection probability.
    Uses a GradientBoostingClassifier trained on the company's own historical outcomes,
    falling back to a heuristic frequency table if training data is insufficient.
    """
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == current_user.company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    from services.predictive_dialer_service import get_best_call_windows
    return get_best_call_windows(
        session=session,
        company_id=current_user.company_id,
        lead_id=lead_id,
        n_windows=n_windows,
        lookahead_hours=lookahead_hours,
    )

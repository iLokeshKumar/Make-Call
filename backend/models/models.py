from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Index, Numeric, String, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditMixin(SQLModel):
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")
    updated_by: Optional[int] = Field(default=None, foreign_key="users.id")


class Company(AuditMixin, table=True):
    __tablename__ = "companies"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=200)
    slug: str = Field(index=True, unique=True, max_length=120)
    domain: Optional[str] = Field(default=None, index=True, max_length=255)
    website: Optional[str] = Field(default=None, max_length=255)
    logo_url: Optional[str] = None
    primary_color: Optional[str] = Field(default=None, max_length=20)
    status: str = Field(default="active", max_length=30)
    subscription_tier: str = Field(default="starter", max_length=50)
    max_users: int = Field(default=10)

    # Phase 4.1: Sub-account hierarchy
    parent_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    max_concurrent_calls: int = Field(default=5)
    daily_call_cap: Optional[int] = Field(default=None)  # None = unlimited

    # Phase 4.4: Data residency
    routing_region: str = Field(default="global", max_length=20)  # "global" | "india"
    
    contact_email: Optional[str] = Field(default=None, max_length=255)
    phone: Optional[str] = Field(default=None, max_length=30)
    address: Optional[str] = Field(default=None, max_length=400)
    city: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=100)
    country: Optional[str] = Field(default=None, max_length=100)
    pincode: Optional[str] = Field(default=None, max_length=20)
    gst_number: Optional[str] = Field(default=None, max_length=50)
    pan_number: Optional[str] = Field(default=None, max_length=20)
    nature_of_business: Optional[str] = Field(default=None, max_length=255)
    vat_number: Optional[str] = Field(default=None, max_length=50)
    cin_number: Optional[str] = Field(default=None, max_length=50)


class User(AuditMixin, table=True):
    __table_args__ = (
        UniqueConstraint("username_normalized", name="uq_users_username_normalized"),
    )
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    email: str = Field(index=True, unique=True, max_length=255)
    username: Optional[str] = Field(default=None, index=True, max_length=100)
    username_normalized: Optional[str] = Field(default=None, index=True, max_length=100)
    password_hash: str
    first_name: Optional[str] = Field(default=None, max_length=100)
    last_name: Optional[str] = Field(default=None, max_length=100)
    phone: Optional[str] = Field(default=None, max_length=30)
    profile_picture_url: Optional[str] = Field(default=None, max_length=500)
    is_active: bool = Field(default=True)
    email_verified: bool = Field(default=False)
    mfa_enabled: bool = Field(default=False)
    mfa_secret: Optional[str] = None
    mfa_disable_otp: Optional[str] = Field(default=None, max_length=16)
    reveal_code: Optional[str] = Field(default=None, max_length=6)
    reveal_code_expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    token_version: int = Field(default=0, index=True)
    last_login_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    email_verification_token: Optional[str] = None
    email_verification_expires_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class Role(AuditMixin, table=True):
    __tablename__ = "roles"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_roles_company_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=100)
    description: Optional[str] = None
    is_system: bool = Field(default=False)


class Permission(SQLModel, table=True):
    __tablename__ = "permissions"

    key: str = Field(primary_key=True, max_length=100)
    module: str = Field(max_length=50)
    description: str


class RolePermission(SQLModel, table=True):
    __tablename__ = "role_permissions"

    role_id: int = Field(foreign_key="roles.id", primary_key=True)
    permission_key: str = Field(foreign_key="permissions.key", primary_key=True)


class UserRole(SQLModel, table=True):
    __tablename__ = "user_roles"

    user_id: int = Field(foreign_key="users.id", primary_key=True)
    role_id: int = Field(foreign_key="roles.id", primary_key=True)


class Invite(AuditMixin, table=True):
    __tablename__ = "invites"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    email: str = Field(index=True, max_length=255)
    role_id: int = Field(foreign_key="roles.id")
    token: str = Field(unique=True, index=True, max_length=255)
    status: str = Field(default="pending", max_length=30)
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    invited_by: int = Field(foreign_key="users.id")
    accepted_by: Optional[int] = Field(default=None, foreign_key="users.id")
    accepted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class Account(AuditMixin, table=True):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_accounts_company_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    website: Optional[str] = Field(default=None, max_length=255)
    domain: Optional[str] = Field(default=None, max_length=255, index=True)
    industry: Optional[str] = Field(default=None, max_length=100)
    company_size: Optional[str] = Field(default=None, max_length=50)
    employee_count: Optional[int] = Field(default=None)
    city: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=100)
    country: Optional[str] = Field(default=None, max_length=100)
    notes: Optional[str] = None
    is_active: bool = Field(default=True)


class Lead(AuditMixin, table=True):
    __tablename__ = "leads"
    __table_args__ = (

        Index(
            "uq_leads_company_phone",
            "company_id", "normalized_phone",
            unique=True,
            postgresql_where=Column("deleted_at").is_(None),
        ),
        Index("ix_leads_company_next_action_due_at", "company_id", "next_action_due_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id", index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    name: str = Field(max_length=200)
    normalized_phone: str = Field(index=True, max_length=30)
    email: Optional[str] = Field(default=None, max_length=255)
    job_title: Optional[str] = Field(default=None, max_length=150)
    industry: Optional[str] = Field(default=None, max_length=100)
    website: Optional[str] = Field(default=None, max_length=255)
    city: Optional[str] = Field(default=None, max_length=100)
    state: Optional[str] = Field(default=None, max_length=100)
    country: Optional[str] = Field(default=None, max_length=100)
    timezone: Optional[str] = Field(default=None, max_length=60)  # IANA tz, e.g. "Asia/Kolkata"
    status: str = Field(default="new", max_length=50)
    qualification_status: str = Field(default="unqualified", max_length=50)
    source: str = Field(default="manual", max_length=100)
    notes: Optional[str] = None
    enrichment_status: str = Field(default="not_enriched", max_length=50)
    lead_score: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(5, 2), nullable=True),
    )
    lead_score_reasons_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    last_enriched_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_outreach_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    product_interest: Optional[str] = None
    budget_range: Optional[str] = Field(default=None, max_length=100)
    timeline: Optional[str] = Field(default=None, max_length=100)
    decision_maker: Optional[str] = Field(default=None, max_length=200)
    next_action: Optional[str] = Field(default=None, max_length=100)
    next_action_due_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    ism_stage: Optional[str] = Field(default="new", max_length=50)
    preferred_language: Optional[str] = Field(default="en", max_length=10)

    company_name: Optional[str] = Field(default=None, max_length=200)
    designation: Optional[str] = Field(default=None, max_length=150)

    billing_address: Optional[str] = Field(default=None, max_length=400)
    pincode: Optional[str] = Field(default=None, max_length=20)
    gst_number: Optional[str] = Field(default=None, max_length=50)
    custom_fields: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class Campaign(AuditMixin, table=True):
    __tablename__ = "campaigns"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id", index=True)
    channel: str = Field(max_length=50)
    objective: str = Field(max_length=100)
    status: str = Field(default="draft", max_length=30)
    description: Optional[str] = None
    target_audience_rule: Optional[str] = None
    start_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    end_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class CampaignSchedule(AuditMixin, table=True):
    """Recurring call schedule for a campaign with daily time windows."""
    __tablename__ = "campaign_schedules"
    __table_args__ = (
        UniqueConstraint("campaign_id", name="uq_campaign_schedules_campaign"),
        Index("ix_campaign_schedules_company_status_next", "company_id", "status", "next_run_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id")
    status: str = Field(default="active", max_length=30)   # active | paused | completed
    start_date: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    end_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    daily_start_hour: int = Field(default=9)      # 0-23
    daily_end_hour: int = Field(default=18)       # 0-23
    days_of_week: list = Field(default_factory=lambda: [0, 1, 2, 3, 4], sa_column=Column(JSON, nullable=False))  # 0=Mon
    timezone: str = Field(default="Asia/Kolkata", max_length=60)
    max_concurrent_calls: int = Field(default=5)
    calls_per_minute: int = Field(default=10)
    last_run_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    next_run_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class MessageTemplate(AuditMixin, table=True):
    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("company_id", "channel", "name", name="uq_templates_company_channel_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    channel: str = Field(max_length=50)
    name: str = Field(max_length=150)
    subject_template: Optional[str] = None
    subject_template_b: Optional[str] = None
    body_template: str
    variables_schema: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    is_active: bool = Field(default=True)


class CampaignStep(AuditMixin, table=True):
    __tablename__ = "campaign_steps"
    __table_args__ = (
        UniqueConstraint("campaign_id", "step_order", name="uq_campaign_steps_order"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    step_order: int
    channel: str = Field(max_length=50)
    template_id: Optional[int] = Field(default=None, foreign_key="message_templates.id")
    delay_hours: int = Field(default=0)
    objective: Optional[str] = Field(default=None, max_length=100)
    ab_split_ratio: float = Field(default=0.5)
    is_active: bool = Field(default=True)


class Interaction(AuditMixin, table=True):
    __tablename__ = "interactions"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id", index=True)
    call_task_id: Optional[int] = Field(default=None, foreign_key="call_tasks.id", index=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id", index=True)
    parent_interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    type: str = Field(max_length=50)
    channel: Optional[str] = Field(default=None, max_length=50)
    direction: Optional[str] = Field(default=None, max_length=20)
    source: Optional[str] = Field(default=None, max_length=50)
    content: Optional[str] = None
    transcript: Optional[str] = None
    recording_url: Optional[str] = None
    recording_duration: Optional[int] = None  # seconds
    delivery_status: Optional[str] = Field(default=None, max_length=30)
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    session_id: Optional[str] = Field(default=None, index=True, max_length=255)
    engine_name: Optional[str] = Field(default="voice_call", max_length=50)
    status: str = Field(default="active", max_length=30)
    started_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    ended_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class ASRSegment(AuditMixin, table=True):
    __tablename__ = "asr_segments"

    id: Optional[int] = Field(default=None, primary_key=True)
    interaction_id: int = Field(foreign_key="interactions.id", index=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    start: Optional[float] = Field(default=None)
    end: Optional[float] = Field(default=None)
    text: Optional[str] = Field(default=None, max_length=2000)
    word_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class CampaignRecipient(AuditMixin, table=True):
    __tablename__ = "campaign_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_recipient"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    campaign_id: int = Field(foreign_key="campaigns.id", index=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    status: str = Field(default="pending", max_length=30)
    current_step: int = Field(default=1)
    next_run_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_contact_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    ab_variant: Optional[str] = Field(default=None, max_length=2)

    processing_started_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class CallTask(AuditMixin, table=True):
    __tablename__ = "call_tasks"
    __table_args__ = (
        Index("ix_call_tasks_company_status_scheduled_at", "company_id", "status", "scheduled_at"),
        Index("ix_call_tasks_company_retry_after", "company_id", "retry_after"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id", index=True)
    campaign_step_id: Optional[int] = Field(default=None, foreign_key="campaign_steps.id", index=True)
    campaign_recipient_id: Optional[int] = Field(default=None, foreign_key="campaign_recipients.id", index=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id", index=True)
    assigned_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    status: str = Field(default="pending", max_length=30)
    scheduled_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    started_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    retry_after: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=3)
    last_outcome: Optional[str] = Field(default=None, max_length=100)
    batch_id: Optional[str] = Field(default=None, index=True, max_length=100)
    outcome_confidence: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(5, 2), nullable=True),
    )
    dialer_source: Optional[str] = Field(default=None, max_length=100)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    notes: Optional[str] = None


class Product(AuditMixin, table=True):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("company_id", "sku", name="uq_products_company_sku"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    sku: Optional[str] = Field(default=None, max_length=100)
    stock: int = Field(default=0)
    price: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(12, 2), nullable=False),
    )
    currency: str = Field(default="INR", max_length=10)
    note: Optional[str] = None
    is_active: bool = Field(default=True)
    # Catalog / classification
    brand: Optional[str] = Field(default=None, max_length=100)
    category: Optional[str] = Field(default=None, max_length=100)
    subcategory: Optional[str] = Field(default=None, max_length=100)
    product_line: Optional[str] = Field(default=None, max_length=100)
    model_number: Optional[str] = Field(default=None, max_length=100)
    description: Optional[str] = None
    # Pricing tiers
    mrp: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(12, 2), nullable=True),
    )
    cost_price: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(12, 2), nullable=True),
    )
    min_price: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(12, 2), nullable=True),
    )
    # Tax / compliance
    hsn_code: Optional[str] = Field(default=None, max_length=20)
    tax_rate: Optional[Decimal] = Field(
        default=None,
        sa_column=Column(Numeric(5, 2), nullable=True),
    )
    unit: Optional[str] = Field(default=None, max_length=30)  # piece, box, set, kg …
    # Logistics
    reorder_level: Optional[int] = Field(default=None)
    warranty_months: Optional[int] = Field(default=None)
    # Media & extras
    image_url: Optional[str] = Field(default=None, max_length=500)
    attributes: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class LeadRequirement(AuditMixin, table=True):
    __tablename__ = "lead_requirements"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    use_case: Optional[str] = None
    budget_range: Optional[str] = Field(default=None, max_length=100)
    timeline: Optional[str] = Field(default=None, max_length=100)
    decision_maker: Optional[str] = Field(default=None, max_length=200)
    competitors: Optional[str] = None
    pain_points: Optional[str] = None
    required_products: Optional[str] = None
    notes: Optional[str] = None
    structured_data: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class Appointment(AuditMixin, table=True):
    __tablename__ = "appointments"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    appointment_time: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    status: str = Field(default="scheduled", max_length=50)
    notes: Optional[str] = None
    meeting_link: Optional[str] = None
    calendar_event_id: Optional[str] = Field(default=None, max_length=255)


class Outcome(AuditMixin, table=True):
    __tablename__ = "outcomes"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    type: str = Field(max_length=50)
    stage: str = Field(default="interest", max_length=50)
    potential_value: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(12, 2), nullable=False),
    )
    probability: Decimal = Field(
        default=Decimal("0.00"),
        sa_column=Column(Numeric(5, 2), nullable=False),
    )
    notes: Optional[str] = None


class Quote(AuditMixin, table=True):
    __tablename__ = "quotes"
    __table_args__ = (
        UniqueConstraint("company_id", "quote_number", name="uq_quotes_company_number"),
        Index("uq_quotes_company_tracking_token", "company_id", "tracking_token", unique=True),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id", index=True)
    quote_number: str = Field(max_length=50, index=True)
    status: str = Field(default="draft", max_length=30)
    currency: str = Field(default="INR", max_length=10)
    subtotal: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    discount_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    tax_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    total_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    valid_until: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    sent_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    opened_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    accepted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    rejected_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    tracking_token: Optional[str] = Field(default=None, index=True, max_length=255)
    pdf_path: Optional[str] = None
    notes: Optional[str] = None
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class QuoteItem(AuditMixin, table=True):
    __tablename__ = "quote_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    quote_id: int = Field(foreign_key="quotes.id", index=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    product_id: Optional[int] = Field(default=None, foreign_key="products.id", index=True)
    product_name_snapshot: str = Field(max_length=200)
    sku_snapshot: Optional[str] = Field(default=None, max_length=100)
    quantity: int = Field(default=1)
    unit_price: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    discount_percent: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(5, 2), nullable=False))
    line_total: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    notes: Optional[str] = None


class ProposalRequest(AuditMixin, table=True):
    __tablename__ = "proposal_requests"
    __table_args__ = (
        Index("ix_proposal_requests_company_lead_status", "company_id", "lead_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    requirement_id: Optional[int] = Field(default=None, foreign_key="lead_requirements.id", index=True)
    quote_id: Optional[int] = Field(default=None, foreign_key="quotes.id", index=True)
    status: str = Field(default="draft", max_length=40)
    intent_type: str = Field(default="quote", max_length=40)
    intent_confidence: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(5, 2), nullable=False))
    source_channel: Optional[str] = Field(default=None, max_length=40)
    request_text: Optional[str] = None
    spec_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    solution_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    pricing_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    validation_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    tabular_scores_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class ProposalDocument(AuditMixin, table=True):
    __tablename__ = "proposal_documents"
    __table_args__ = (
        Index("ix_proposal_documents_company_request", "company_id", "proposal_request_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    proposal_request_id: int = Field(foreign_key="proposal_requests.id", index=True)
    quote_id: Optional[int] = Field(default=None, foreign_key="quotes.id", index=True)
    version: int = Field(default=1)
    status: str = Field(default="draft", max_length=40)
    title: str = Field(max_length=250)
    sections_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    validation_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    pdf_path: Optional[str] = None
    sent_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class ProposalTrainingSample(AuditMixin, table=True):
    """Excel-seeded labelled rows used to train the TabPFN proposal scorer.

    Each row holds a `_feature_row`-shaped feature dict plus a win/loss label.
    These are merged with live proposal/quote history so TabPFN has data even
    before the company has accumulated real outcomes.
    """
    __tablename__ = "proposal_training_samples"
    __table_args__ = (
        Index("ix_proposal_training_samples_company", "company_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    label: str = Field(max_length=20)  # "won" | "not_won"
    features_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    source: str = Field(default="excel_seed", max_length=40)


class CompanySetting(AuditMixin, table=True):
    __tablename__ = "company_settings"
    __table_args__ = (
        UniqueConstraint("company_id", "key", name="uq_company_settings_company_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    key: str = Field(max_length=150)
    value: str
    is_secret: bool = Field(default=False)


class CompanySettingAudit(AuditMixin, table=True):
    __tablename__ = "company_setting_audits"
    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    key: str = Field(max_length=150)
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    changed_by: Optional[int] = Field(default=None, foreign_key="users.id")
    note: Optional[str] = None


class ASRCleanupRun(SQLModel, table=True):
    """Records each ASR cleanup execution for monitoring and audits."""
    __tablename__ = "asr_cleanup_runs"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    run_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    cutoff_date: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    deleted_count: int = Field(default=0)
    duration_seconds: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(12, 2), nullable=True))
    success: bool = Field(default=True)
    error_text: Optional[str] = None


class CompanyPrompt(AuditMixin, table=True):
    """Versioned company prompts for AI agents. Supports simple versioning and activation."""
    __tablename__ = "company_prompts"
    __table_args__ = (
        Index("ix_company_prompts_company_version", "company_id", "version"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    version: int = Field(default=1)
    prompt_text: str
    author_id: Optional[int] = Field(default=None, foreign_key="users.id")
    change_reason: Optional[str] = None
    is_active: bool = Field(default=False)
    published_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class VoiceAgent(AuditMixin, table=True):
    __tablename__ = "voice_agents"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_voice_agents_company_name"),
        Index("ix_voice_agents_company_default", "company_id", "is_default"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=150)
    description: Optional[str] = None
    status: str = Field(default="active", max_length=30)
    is_default: bool = Field(default=False)
    agent_type: str = Field(default="prompt", max_length=30)
    version: int = Field(default=1)
    archived_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class VoiceAgentRuntimeConfig(AuditMixin, table=True):
    __tablename__ = "voice_agent_runtime_configs"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_voice_agent_runtime_agent"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: int = Field(foreign_key="voice_agents.id", index=True)
    stt_provider: Optional[str] = Field(default=None, max_length=50)
    llm_provider: Optional[str] = Field(default=None, max_length=50)
    tts_provider: Optional[str] = Field(default=None, max_length=50)
    telephony_engine: Optional[str] = Field(default=None, max_length=50)
    voice_preset_id: Optional[int] = Field(default=None, foreign_key="voice_agent_voice_presets.id")
    language: Optional[str] = Field(default="en-IN", max_length=20)
    ai_verbosity: Optional[str] = Field(default="2", max_length=10)
    max_call_duration_seconds: Optional[int] = Field(default=None)
    silence_reengage_seconds: Optional[int] = Field(default=None)
    business_hours_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    runtime_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))


class VoiceAgentPromptVersion(AuditMixin, table=True):
    __tablename__ = "voice_agent_prompt_versions"
    __table_args__ = (
        Index("ix_voice_agent_prompt_versions_active", "agent_id", "is_active"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: int = Field(foreign_key="voice_agents.id", index=True)
    version: int = Field(default=1)
    name: str = Field(default="Default prompt", max_length=150)
    system_prompt: str
    instructions: Optional[str] = None
    is_active: bool = Field(default=True)
    traffic_split: Optional[int] = Field(default=0)
    published_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class VoiceAgentExecutionEvent(SQLModel, table=True):
    __tablename__ = "voice_agent_execution_events"
    __table_args__ = (
        Index("ix_voice_agent_events_company_agent_created", "company_id", "agent_id", "created_at"),
        Index("ix_voice_agent_events_interaction", "interaction_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    call_task_id: Optional[int] = Field(default=None, foreign_key="call_tasks.id", index=True)
    event_type: str = Field(max_length=80)
    provider: Optional[str] = Field(default=None, max_length=50)
    summary: Optional[str] = None
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class VoiceAgentExtractionTemplate(AuditMixin, table=True):
    __tablename__ = "voice_agent_extraction_templates"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: int = Field(foreign_key="voice_agents.id", index=True)
    name: str = Field(max_length=150)
    instructions: Optional[str] = None
    extraction_schema: dict = Field(default_factory=dict, sa_column=Column("schema_json", JSON, nullable=False))
    is_active: bool = Field(default=True)


class VoiceAgentExtractionResult(SQLModel, table=True):
    __tablename__ = "voice_agent_extraction_results"
    __table_args__ = (
        Index("ix_voice_agent_extraction_results_interaction", "interaction_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: int = Field(foreign_key="voice_agents.id", index=True)
    template_id: Optional[int] = Field(default=None, foreign_key="voice_agent_extraction_templates.id")
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    output_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="completed", max_length=30)
    error: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class VoiceAgentTool(AuditMixin, table=True):
    __tablename__ = "voice_agent_tools"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_voice_agent_tools_company_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id", index=True)
    name: str = Field(max_length=120)
    description: Optional[str] = None
    tool_type: str = Field(default="custom_http", max_length=40)
    input_schema_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    http_method: Optional[str] = Field(default=None, max_length=10)
    url: Optional[str] = None
    headers_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    body_template: Optional[str] = None
    is_active: bool = Field(default=True)
    last_test_result_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class VoiceAgentGraph(AuditMixin, table=True):
    __tablename__ = "voice_agent_graphs"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_voice_agent_graph_agent"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: int = Field(foreign_key="voice_agents.id", index=True)
    graph_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    is_enabled: bool = Field(default=False)
    validation_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    published_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class VoiceAgentVoicePreset(AuditMixin, table=True):
    __tablename__ = "voice_agent_voice_presets"
    __table_args__ = (
        UniqueConstraint("company_id", "provider", "voice_id", name="uq_voice_presets_company_provider_voice"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=150)
    provider: str = Field(max_length=50)
    voice_id: str = Field(max_length=200)
    model: Optional[str] = Field(default=None, max_length=100)
    language: Optional[str] = Field(default=None, max_length=20)
    sample_url: Optional[str] = None
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    is_active: bool = Field(default=True)


class ProviderPhoneNumber(AuditMixin, table=True):
    """Phone numbers purchased/registered from telephony providers."""
    __tablename__ = "provider_phone_numbers"
    __table_args__ = (
        UniqueConstraint("company_id", "provider", "number", name="uq_provider_phone_numbers_company_provider_number"),
        Index("ix_provider_phone_numbers_company_status", "company_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    provider: str = Field(max_length=30)           # twilio | plivo | exotel | vobiz
    number: str = Field(max_length=30)             # E.164 format e.g. +14155552671
    sid: Optional[str] = Field(default=None, max_length=200)  # provider-side SID/UUID
    friendly_name: Optional[str] = Field(default=None, max_length=150)
    capabilities: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))  # {voice, sms, mms}
    status: str = Field(default="active", max_length=30)  # active | released
    assigned_agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id", index=True)
    monthly_cost: Optional[str] = Field(default=None, max_length=20)
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class SIPTrunk(AuditMixin, table=True):
    """SIP trunk configuration for bring-your-own-carrier."""
    __tablename__ = "sip_trunks"
    __table_args__ = (
        UniqueConstraint("company_id", "name", name="uq_sip_trunks_company_name"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=100)
    provider: str = Field(max_length=50)        # generic_sip | twilio_sip | plivo_sip
    host: str = Field(max_length=255)           # sip.example.com
    port: int = Field(default=5060)
    transport: str = Field(default="udp", max_length=10)  # udp | tcp | tls
    username: Optional[str] = Field(default=None, max_length=200)
    password_encrypted: Optional[str] = Field(default=None, max_length=500)
    sip_uri: Optional[str] = Field(default=None, max_length=500)
    outbound_proxy: Optional[str] = Field(default=None, max_length=255)
    codecs: str = Field(default="PCMU,PCMA", max_length=200)
    dtmf_mode: str = Field(default="rfc2833", max_length=30)
    status: str = Field(default="active", max_length=20)
    is_default: bool = Field(default=False)
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class ComplianceApplication(AuditMixin, table=True):
    """India DLT/140-160 compliance application tracking."""
    __tablename__ = "compliance_applications"
    __table_args__ = (
        Index("ix_compliance_applications_company_status", "company_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    application_type: str = Field(max_length=50)    # dlt_140 | dlt_160 | truecaller_verification
    status: str = Field(default="draft", max_length=30)  # draft | submitted | approved | rejected
    provider: str = Field(max_length=30)            # twilio | plivo | exotel | vobiz
    entity_name: str = Field(max_length=200)        # Company/entity name for registration
    entity_id: Optional[str] = Field(default=None, max_length=100)  # DLT entity ID
    header_id: Optional[str] = Field(default=None, max_length=100)  # DLT header ID
    template_id: Optional[str] = Field(default=None, max_length=100)
    document_urls: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    notes: Optional[str] = None
    submitted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class KnowledgeDocument(AuditMixin, table=True):
    """Per-company knowledge base document (stored in DB + indexed in ChromaDB)."""
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "company_id", "collection", "title",
            name="uq_kb_company_collection_title",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    # products | objections | competitors | playbooks | coaching | sops | transcripts
    collection: str = Field(max_length=50, index=True)
    title: str = Field(max_length=300)
    content: str
    tags: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    chroma_doc_id: Optional[str] = Field(default=None, max_length=200)
    is_active: bool = Field(default=True)
    last_indexed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class UserSetting(SQLModel, table=True):
    __tablename__ = "user_settings"
    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_user_settings_user_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    key: str = Field(max_length=150)
    value: str
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ActivityEvent(SQLModel, table=True):
    __tablename__ = "activity_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id", index=True)
    event_type: str = Field(max_length=100)
    channel: Optional[str] = Field(default=None, max_length=50)
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class EngagementEvent(SQLModel, table=True):
    __tablename__ = "engagement_events"
    __table_args__ = (
        Index("ix_engagement_events_company_created_at", "company_id", "created_at"),
        Index("ix_engagement_events_interaction_id", "interaction_id"),
        Index("ix_engagement_events_quote_id", "quote_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id")
    quote_id: Optional[int] = Field(default=None, foreign_key="quotes.id")
    channel: Optional[str] = Field(default=None, max_length=50)
    event_type: str = Field(max_length=100)
    payload: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SentimentEvent(SQLModel, table=True):
    __tablename__ = "sentiment_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    interaction_id: str = Field(index=True, max_length=120)
    company_id: int = Field(foreign_key="companies.id", index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class IsmActivityEvent(SQLModel, table=True):
    """Real-time ISM agent decision feed for the live activity dashboard.

    One row per ISM action — dispatched email/whatsapp/call, handoff,
    auto-close decision, exhaustion outcome.  Consumed by the
    /ws/ism-activity/{company_id} WebSocket endpoint.  Cleaned up by the
    automation worker after 4 hours (same retention as CallStatusEvent).
    """
    __tablename__ = "ism_activity_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    lead_name: Optional[str] = Field(default=None, max_length=200)
    stage: Optional[str] = Field(default=None, max_length=40)
    # "dispatched_email" | "dispatched_whatsapp" | "dispatched_call" |
    # "handoff" | "auto_closed_won" | "auto_closed_lost" | "skipped"
    action: str = Field(max_length=60)
    # Short human-readable reason, surfaced in the dashboard feed.
    reason: Optional[str] = Field(default=None, max_length=400)
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CallStatusEvent(SQLModel, table=True):
    """Real-time call lifecycle events for the live call monitor dashboard.

    One row per transition: ringing → connected → ended.
    Consumed by the /ws/call-monitor/{company_id} WebSocket endpoint.
    Cleaned up by the automation worker after 4 hours.
    """
    __tablename__ = "call_status_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id", index=True)
    call_task_id: Optional[int] = Field(default=None, foreign_key="call_tasks.id")
    interaction_id: Optional[str] = Field(default=None, max_length=120)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id")
    lead_name: Optional[str] = Field(default=None, max_length=200)
    # "ringing" | "connected" | "ended"
    status: str = Field(max_length=30)

    outcome: Optional[str] = Field(default=None, max_length=100)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class WebhookConfig(AuditMixin, table=True):
    """Per-company outbound webhook registrations.
    HTTP delivery fan-out: on each call-end / ISM-event / tool-exec
    the delivery loop POSTs JSON to every active URL subscribed to that event type.
    """
    __tablename__ = "webhook_configs"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=150)
    url: str
    events: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    secret: Optional[str] = None               # HMAC signing secret (min 16 chars)
    is_active: bool = Field(default=True)
    timeout_seconds: int = Field(default=10)

    # Event-filter hints (optional, narrow scope)
    agent_filter: Optional[str] = Field(default=None, max_length=50)   # "voice_agent" | None
    outcome_filter: Optional[str] = Field(default=None, max_length=50) # "completed" | None


class WebhookDeliveryLog(SQLModel, table=True):
    """One row per HTTP delivery attempt. Used for debugging failed webhooks
    and the delivery-retry dashboard."""
    __tablename__ = "webhook_delivery_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    webhook_id: int = Field(foreign_key="webhook_configs.id", index=True)
    event_type: str = Field(max_length=60)
    payload_hash: str = Field(max_length=64)    # sha256 of payload body
    http_status: Optional[int] = Field(default=None)  # 200, 404, 500, timeout etc.
    response_ms: Optional[int] = Field(default=None)
    error: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class AnalyticsAlert(AuditMixin, table=True):
    __tablename__ = "analytics_alerts"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    metric: str = Field(max_length=100)
    threshold: Decimal = Field(sa_column=Column(Numeric(12, 2), nullable=False))
    direction: str = Field(default="gte", max_length=10)  # gte or lte
    channel: str = Field(default="email", max_length=50)
    enabled: bool = Field(default=True)
    last_triggered_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class LatencyLog(SQLModel, table=True):
    __tablename__ = "latencylog"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    engine: Optional[str] = Field(default=None, max_length=120)
    stt_ms: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    llm_ms: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    tts_ms: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    total_ms: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    stt_provider: Optional[str] = Field(default=None, max_length=80)
    stt_model: Optional[str] = Field(default=None, max_length=120)
    llm_provider: Optional[str] = Field(default=None, max_length=80)
    llm_model: Optional[str] = Field(default=None, max_length=120)
    tts_provider: Optional[str] = Field(default=None, max_length=80)
    tts_model: Optional[str] = Field(default=None, max_length=120)
    notes: Optional[str] = None
    trace_id: Optional[str] = Field(default=None, max_length=64)
    span_id: Optional[str] = Field(default=None, max_length=32)
    turn_index: Optional[int] = Field(default=None)
    span_status: Optional[str] = Field(default=None, max_length=30)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class LoginHistory(SQLModel, table=True):
    __tablename__ = "login_history"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    email: str = Field(index=True, max_length=255)
    event_type: str = Field(default="login_success", max_length=50)
    success: bool = Field(default=True)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    location: Optional[str] = Field(default=None, max_length=200)
    geo_data: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    user_agent: Optional[str] = None
    failure_reason: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OptOut(SQLModel, table=True):
    __tablename__ = "opt_outs"
    __table_args__ = (
        UniqueConstraint("company_id", "lead_id", "channel", name="uq_opt_out_company_lead_channel"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    channel: str = Field(max_length=50)
    reason: Optional[str] = None
    opted_out_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    actor_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    entity_type: str = Field(max_length=100)
    entity_id: Optional[int] = Field(default=None, index=True)
    action: str = Field(max_length=50)
    old_values: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    new_values: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    ip_address: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ObjectionEntry(AuditMixin, table=True):
    """Company-scoped objection library.

    Populated automatically after each call via post_call_service.
    Injected into the voice pipeline system prompt at call start so Rio
    knows how to handle recurring objections.
    """
    __tablename__ = "objection_entries"
    __table_args__ = (
        UniqueConstraint("company_id", "objection_key", name="uq_objection_company_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    # Canonical short form of the objection, like "too expensive"
    objection_key: str = Field(max_length=200)
    # Human-readable label shown in the UI (same as key unless edited)
    objection_text: str = Field(max_length=500)
    # One of: price | competitor | timing | need | general
    category: str = Field(default="general", max_length=50)
    # Suggested rebuttal (editable by admins)
    rebuttal: Optional[str] = None
    # How many times raised (auto-incremented on extraction)
    frequency_count: int = Field(default=1)
    source_interaction_id: Optional[int] = Field(
        default=None, foreign_key="interactions.id", index=True
    )
    is_active: bool = Field(default=True)


class CallCoachScore(AuditMixin, table=True):
    """AI-scored evaluation of the voice agent's performance on a call.

    Populated automatically post-call by call_coach_service.
    Used to identify weak areas and auto-tune the system prompt.
    """
    __tablename__ = "call_coach_scores"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    interaction_id: int = Field(foreign_key="interactions.id", index=True, unique=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)

    # Dimension scores 0-10
    score_rapport: Optional[int] = None # opening / tone
    score_discovery: Optional[int] = None # questions asked, needs uncovered
    score_objection_handling: Optional[int] = None
    score_value_proposition: Optional[int] = None
    score_closing: Optional[int] = None # clear CTA / next step set
    score_overall: Optional[int] = None # weighted composite

    # LLM-generated summary and recommended prompt fix
    strengths: Optional[str] = None
    weaknesses: Optional[str] = None
    prompt_suggestion: Optional[str] = None      # the actual improved system-prompt snippet
    prompt_applied: bool = Field(default=False)  # True once auto-tune writes it


class CallEvalResult(AuditMixin, table=True):
    """LLM-as-judge evaluation of a call across 6 business axes.

    Auto-populated post-call via call_eval_service.
    Provider/model determined by EVAL_JUDGE_PROVIDER / EVAL_JUDGE_MODEL company settings.
    """
    __tablename__ = "call_eval_results"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    interaction_id: int = Field(foreign_key="interactions.id", index=True, unique=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)

    judge_provider: str = Field(default="mistral", max_length=50)
    judge_model: str = Field(default="mistral-large-latest", max_length=100)


    score_call_summary: Optional[int] = None
    score_lead_qualification: Optional[int] = None
    score_next_action: Optional[int] = None
    score_tool_use_honesty: Optional[int] = None
    score_tone_brand: Optional[int] = None
    score_handoff_escalation: Optional[int] = None
    score_overall: Optional[float] = None  # mean of non-null axes

    passed: bool = Field(default=False)
    reasoning: Optional[str] = None
    failures_json: Optional[str] = Field(default=None, max_length=2000)  # JSON array of axis names

    ran_at: Optional[datetime] = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class CompetitorMention(AuditMixin, table=True):
    """Tracks every time a competitor is mentioned on a call.

    Populated in real-time by the voice pipeline and post-call by the LLM extractor.
    Used to feed counter-scripts into the AI system prompt.
    """
    __tablename__ = "competitor_mentions"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)

    competitor_name: str = Field(max_length=200, index=True)

    mention_snippet: Optional[str] = Field(default=None, max_length=500)

    counter_script: Optional[str] = None

    source: str = Field(default="post_call", max_length=50)
    detected_at: Optional[datetime] = Field(default_factory=utc_now)


class UsageEvent(SQLModel, table=True):
    """Tracks AI service consumption across all providers and call sites."""
    __tablename__ = "usage_events"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)

    service_type: str = Field(max_length=20)           # "llm" | "stt" | "tts"
    provider: str = Field(max_length=50)               # "groq" | "claude" | "deepgram" …
    model: Optional[str] = Field(default=None, max_length=120)

    prompt_tokens: Optional[int] = Field(default=None)
    completion_tokens: Optional[int] = Field(default=None)
    total_tokens: Optional[int] = Field(default=None)
    characters: Optional[int] = Field(default=None)    # TTS characters synthesised
    audio_seconds: Optional[float] = Field(default=None)  # STT/TTS duration

    context: Optional[str] = Field(default=None, max_length=60)  # "voice_turn" | "post_call" | "eval" …
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"
    message: Optional[str] = None


class CompanyRegister(SQLModel):
    company_name: str
    company_slug: str
    admin_email: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: str
    phone_number: Optional[str] = None


class InviteCreate(SQLModel):
    email: str
    role_id: int
    expires_in_hours: int = 72


class InviteAccept(SQLModel):
    token: str
    email: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None


class LeadCreate(SQLModel):
    name: str
    normalized_phone: str
    email: Optional[str] = None
    status: Optional[str] = "new"
    notes: Optional[str] = None
    owner_user_id: Optional[int] = None


class LeadUpdate(SQLModel):
    name: Optional[str] = None
    normalized_phone: Optional[str] = None
    email: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    owner_user_id: Optional[int] = None
    preferred_language: Optional[str] = None
    timezone: Optional[str] = None

class ProductCreate(SQLModel):
    name: str
    sku: Optional[str] = None
    stock: int = 0
    price: Decimal = Decimal("0.00")
    currency: str = "INR"
    note: Optional[str] = None
    is_active: bool = True
    brand: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    product_line: Optional[str] = None
    model_number: Optional[str] = None
    description: Optional[str] = None
    mrp: Optional[Decimal] = None
    cost_price: Optional[Decimal] = None
    min_price: Optional[Decimal] = None
    hsn_code: Optional[str] = None
    tax_rate: Optional[Decimal] = None
    unit: Optional[str] = None
    reorder_level: Optional[int] = None
    warranty_months: Optional[int] = None
    image_url: Optional[str] = None
    attributes: Optional[dict] = None

class ProductUpdate(SQLModel):
    name: Optional[str] = None
    sku: Optional[str] = None
    stock: Optional[int] = None
    price: Optional[Decimal] = None
    currency: Optional[str] = None
    note: Optional[str] = None
    is_active: Optional[bool] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    product_line: Optional[str] = None
    model_number: Optional[str] = None
    description: Optional[str] = None
    mrp: Optional[Decimal] = None
    cost_price: Optional[Decimal] = None
    min_price: Optional[Decimal] = None
    hsn_code: Optional[str] = None
    tax_rate: Optional[Decimal] = None
    unit: Optional[str] = None
    reorder_level: Optional[int] = None
    warranty_months: Optional[int] = None
    image_url: Optional[str] = None
    attributes: Optional[dict] = None

class Feedback(AuditMixin, table=True):
    __tablename__ = "feedback"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    submitted_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id")

    # call_review | csat | general | bug_report | feature_request
    feedback_type: str = Field(default="general", max_length=50)
    # internal | customer
    source: str = Field(default="internal", max_length=20)

    rating: Optional[int] = Field(default=None) # 1–5
    comment: Optional[str] = None
    # interested | not_interested | callback | voicemail | no_answer | do_not_call
    disposition: Optional[str] = Field(default=None, max_length=50)
    tags: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Public CSAT link support
    token: Optional[str] = Field(
        default=None,
        sa_column=Column(String(100), unique=True, nullable=True, index=True),
    )
    token_expires_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    responded_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    # pending (CSAT not yet answered) | submitted | expired
    status: str = Field(default="submitted", max_length=20)
    assignee_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    close_loop_status: str = Field(default="none", max_length=30)  # none | open | in_progress | resolved
    status_note: Optional[str] = None
    follow_up_task_id: Optional[int] = Field(default=None, foreign_key="call_tasks.id", index=True)


class EmailOutbox(AuditMixin, table=True):
    __tablename__ = "email_outbox"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_email_outbox_dedupe_key"),
        Index("ix_email_outbox_status_next", "status", "next_attempt_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    actor_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    feedback_id: Optional[int] = Field(default=None, foreign_key="feedback.id", index=True)
    dedupe_key: Optional[str] = Field(default=None, max_length=200, index=True)

    to_email: str = Field(max_length=500)
    subject: str = Field(max_length=500)
    body: str
    html_body: Optional[str] = None
    company_name: Optional[str] = Field(default=None, max_length=200)
    attachment_paths: Optional[list[str]] = Field(default=None, sa_column=Column(JSON, nullable=True))

    status: str = Field(default="pending", max_length=20)  # pending | sent | failed
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=5)
    next_attempt_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    sent_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_issue: Optional[str] = None

    request_id: Optional[str] = Field(default=None, max_length=64, index=True)


class UiLatencyLog(SQLModel, table=True):
    """Frontend timing beacon for SLO #2 (login → dashboard p95).

    Populated by the apiFetch beacon at `frontend/src/utils/uiLatency.ts`
    on `window.load` of `/`.  Cookie-auth only.  No PII.
    """
    __tablename__ = "ui_latency_log"
    __table_args__ = (
        Index("ix_ui_latency_log_company_created", "company_id", "created_at"),
        Index("ix_ui_latency_log_route_event", "route", "event"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    route: str = Field(max_length=120)              # "/" | "/leads" etc.
    event: str = Field(max_length=20)               # "ttfb" | "fmp" | "tti"
    duration_ms: int
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class FeedbackPublicAudit(SQLModel, table=True):
    __tablename__ = "feedback_public_audit"
    __table_args__ = (
        Index("ix_feedback_public_audit_created_at", "created_at"),
        Index("ix_feedback_public_audit_token", "token_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: Optional[int] = Field(default=None, foreign_key="companies.id", index=True)
    feedback_id: Optional[int] = Field(default=None, foreign_key="feedback.id", index=True)
    action: str = Field(max_length=30)  # view | submit
    status: str = Field(max_length=30)  # ok | invalid_token | expired | already_submitted | rate_limited | error
    token_key: Optional[str] = Field(default=None, max_length=120)
    ip_address: Optional[str] = Field(default=None, max_length=64)
    user_agent: Optional[str] = None
    rating: Optional[int] = None
    detail: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    created_by: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    updated_by: Optional[int] = Field(default=None, foreign_key="users.id", index=True)


class BackgroundJob(SQLModel, table=True):
    """
    Persistent job queue backed by PostgreSQL.

    Jobs survive FastAPI process restarts. The automation worker claims rows
    with status='pending', sets status='running', then marks them 'done' or
    'failed'. Stale 'running' rows (started_at older than 10 min) are reset
    to 'pending' at the start of each worker cycle so they are retried.

    Supported job_types:
      - post_call_workflow: run extract_and_save_requirements + dispatch_next_action
    """
    __tablename__ = "background_jobs"
    __table_args__ = (
        Index(
            "ix_background_jobs_company_status_run_after",
            "company_id", "status", "run_after",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    job_type: str = Field(max_length=100)
    status: str = Field(default="pending", max_length=30)  # pending | running | done | failed | dead_letter
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON))
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=3)
    run_after: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    started_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    finished_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    error: Optional[str] = Field(default=None)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AgentTask(AuditMixin, table=True):
    """
    Durable agent task queue — the universal unit of work for the orchestrator.

    The automation worker picks pending tasks, invokes the assigned agent via
    orchestrator.run_agent(), and writes results back. Tasks that require human
    approval stay in status='awaiting_approval' until a reviewer acts.

    Status lifecycle:
      pending → running → done | failed (re-queued if attempts < max_attempts)
      pending → awaiting_approval → approved → running → done | failed
                                  → rejected  (terminal)
    """
    __tablename__ = "agent_tasks"
    __table_args__ = (
        Index("ix_agent_tasks_company_status_run_after", "company_id", "status", "run_after"),
        Index("ix_agent_tasks_company_agent_status", "company_id", "assigned_agent", "status"),
        UniqueConstraint("idempotency_key", name="uq_agent_tasks_idempotency_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)

    # What and who
    task_type: str = Field(max_length=100)          # enrich_lead | send_email | qualify_lead | and so on
    assigned_agent: str = Field(max_length=100)     # enrichment | knowledge | campaign | quote | and so on
    priority: int = Field(default=5)                # 1=highest, 10=lowest

    # Lifecycle
    status: str = Field(default="pending", max_length=30)
    # pending | running | awaiting_approval | approved | rejected | done | failed

    # Payload
    input_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    output_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    # Approval gate
    requires_approval: bool = Field(default=False)

    # Deduplication
    idempotency_key: Optional[str] = Field(default=None, max_length=200, index=True)

    # Distributed tracing — inherited from request_id_var when the task is created inside an HTTP request, or from the parent task's trace when an executor enqueues a sub-task. See services/agent/agent_task_service.create_agent_task.
    trace_id: Optional[str] = Field(default=None, max_length=64, index=True)

    attempts: int = Field(default=0)
    max_attempts: int = Field(default=3)
    run_after: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    started_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class AgentApproval(AuditMixin, table=True):
    """
    Human-in-the-loop approval gate for high-stakes agent actions.

    Created when an agent produces a task with requires_approval=True.
    Operators review via the portal and approve or reject. Unreviewed
    approvals expire after expires_at and are auto-rejected by the worker.

    Status lifecycle:
      pending → approved | rejected | expired
    """
    __tablename__ = "agent_approvals"
    __table_args__ = (
        Index("ix_agent_approvals_company_status", "company_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    task_id: int = Field(foreign_key="agent_tasks.id", index=True)

    action_type: str = Field(max_length=100)
    action_summary: str
    action_payload: dict = Field(default_factory=dict, sa_column=Column(JSON))

    status: str = Field(default="pending", max_length=30)
    reviewer_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    reviewed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    reviewer_note: Optional[str] = None

    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))


class CompanyUsage(SQLModel, table=True):
    __tablename__ = "company_usage"
    __table_args__ = (
        UniqueConstraint("company_id", "month", "metric", name="uq_company_usage"),
        Index("ix_company_usage_company_month", "company_id", "month"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    month: str = Field(max_length=7)    # "2026-04"
    metric: str = Field(max_length=50)  # "calls_made" | "emails_sent" | "whatsapp_sent"
    count: int = Field(default=0)
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CompanyFeatureFlag(SQLModel, table=True):
    """Explicit per-company overrides that beat the tier default."""
    __tablename__ = "company_feature_flags"
    __table_args__ = (
        UniqueConstraint("company_id", "feature", name="uq_company_feature_flags"),
        Index("ix_company_feature_flags_company_id", "company_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id")
    feature: str = Field(max_length=100)   # e.g. "whatsapp", "campaigns", "ai_coach"
    enabled: bool = Field(default=True)
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class IsmRule(AuditMixin, table=True):
    """
    ISM rule — data-driven override for stage-based channel selection.

    When the ISM orchestrator evaluates a lead, it first consults the ordered
    list of active rules. The first rule whose `when_json` conditions match
    fires its `then_action`. Rules replace "add a new elif in Python and
    redeploy" with "ops inserts a row."

    Example:
        priority=10  name="vip_high_budget"
        when_json={"stage": "engaged", "budget_usd_min": 50000}
        then_action="dispatch:send_quote"

        priority=20  name="stuck_lead_handoff"
        when_json={"stage": "negotiation", "days_since_contact_min": 7}
        then_action="handoff_to_human"

    when_json DSL (all optional, AND-combined):
        stage: str                              — exact match on Lead.ism_stage
        stages: list[str]                       — any match
        budget_usd_min: int                     — LeadRequirement.budget_range ≥ this
        budget_usd_max: int                     — ≤ this
        urgency: str in {urgent, routine}       — classified from timeline
        days_since_contact_min: int             — lead.last_outreach_at at-least N days ago
        days_since_contact_max: int             — at-most
        has_email: bool                         — lead.email non-empty
        has_phone: bool                         — lead.normalized_phone non-empty
        lead_score_min: float                   — Lead.lead_score ≥ this
        lead_score_max: float                   — ≤ this

    then_action format:
        "advance_to:<stage>"                    — transition lead to <stage>
        "dispatch:<task_type>"                  — enqueue an agent task
        "handoff_to_human"                      — create approval task, stop
        "skip"                                  — no-op (useful for testing)
    """
    __tablename__ = "ism_rules"
    __table_args__ = (
        Index("ix_ism_rules_company_active_priority", "company_id", "is_active", "priority"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    description: Optional[str] = None
    priority: int = Field(default=10)
    when_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    then_action: str = Field(max_length=200)
    is_active: bool = Field(default=True)


class FeedbackCreate(SQLModel):
    lead_id: Optional[int] = None
    interaction_id: Optional[int] = None
    feedback_type: str = "general"
    rating: Optional[int] = None
    comment: Optional[str] = None
    disposition: Optional[str] = None
    tags: Optional[dict] = None


class FeedbackUpdate(SQLModel):
    rating: Optional[int] = None
    comment: Optional[str] = None
    disposition: Optional[str] = None
    tags: Optional[dict] = None
    status: Optional[str] = None
    assignee_user_id: Optional[int] = None
    close_loop_status: Optional[str] = None
    status_note: Optional[str] = None
    follow_up_task_id: Optional[int] = None


class FeedbackCloseLoopUpdate(SQLModel):
    assignee_user_id: Optional[int] = None
    close_loop_status: Optional[str] = None
    status_note: Optional[str] = None
    create_follow_up_task: bool = False


class CsatSendRequest(SQLModel):
    lead_id: int
    interaction_id: Optional[int] = None
    expires_hours: int = 72


class CsatSubmitRequest(SQLModel):
    rating: int          # 1–5
    comment: Optional[str] = None


class CompanySettingUpsert(SQLModel):
    key: str
    value: str
    is_secret: bool = False


class CompanySettingsBulkUpsert(SQLModel):
    items: list[CompanySettingUpsert]


class RoleCreate(SQLModel):
    name: str
    description: Optional[str] = None
    permission_keys: list[str] = []


class RoleUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    permission_keys: Optional[list[str]] = None


class AssignRoleRequest(SQLModel):
    role_id: int


class UserUpdateStatus(SQLModel):
    is_active: bool


class CampaignCreate(SQLModel):
    name: str
    channel: str
    objective: str
    agent_id: Optional[int] = None
    description: Optional[str] = None
    target_audience_rule: Optional[str] = None


class CampaignStepCreate(SQLModel):
    step_order: int
    channel: str
    template_id: Optional[int] = None
    delay_hours: int = 0
    objective: Optional[str] = None


class CampaignStepUpdate(SQLModel):
    channel: Optional[str] = None
    delay_hours: Optional[int] = None
    template_id: Optional[int] = None
    objective: Optional[str] = None


class CampaignStepsReorder(SQLModel):
    step_ids: list[int]


class TemplateCreate(SQLModel):
    channel: str
    name: str
    subject_template: Optional[str] = None
    body_template: str
    variables_schema: Optional[dict] = None


class TemplateRenderRequest(SQLModel):
    lead_id: Optional[int] = None
    quote_id: Optional[int] = None
    product_id: Optional[int] = None


class LeadRequirementUpsert(SQLModel):
    lead_id: int
    interaction_id: Optional[int] = None
    use_case: Optional[str] = None
    budget_range: Optional[str] = None
    timeline: Optional[str] = None
    decision_maker: Optional[str] = None
    competitors: Optional[str] = None
    pain_points: Optional[str] = None
    required_products: Optional[str] = None
    notes: Optional[str] = None
    structured_data: Optional[dict] = None


class QuoteItemCreate(SQLModel):
    product_id: Optional[int] = None
    product_name_snapshot: str
    sku_snapshot: Optional[str] = None
    quantity: int = 1
    unit_price: Decimal = Decimal("0.00")
    discount_percent: Decimal = Decimal("0.00")
    notes: Optional[str] = None


class QuoteCreate(SQLModel):
    lead_id: int
    account_id: Optional[int] = None
    currency: str = "INR"
    valid_until: Optional[datetime] = None
    notes: Optional[str] = None
    items: list[QuoteItemCreate]


class QuoteSendRequest(SQLModel):
    channels: list[str]
    subject: Optional[str] = None
    message: Optional[str] = None


class BulkQuotePdfRequest(SQLModel):
    quote_ids: list[int]


class ProposalDraftRequest(SQLModel):
    lead_id: int
    interaction_id: Optional[int] = None
    request_text: Optional[str] = None
    source_channel: Optional[str] = None
    auto_create_quote: bool = True


class ProposalSendRequest(SQLModel):
    channels: list[str]
    subject: Optional[str] = None
    message: Optional[str] = None
    requires_approval: Optional[bool] = None


class CallTaskCreate(SQLModel):
    lead_id: int
    agent_id: Optional[int] = None
    campaign_id: Optional[int] = None
    campaign_step_id: Optional[int] = None
    assigned_user_id: Optional[int] = None
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = None


class CallTaskStatusUpdate(SQLModel):
    interaction_id: Optional[int] = None
    outcome: Optional[str] = None


class BatchCallTaskCreate(SQLModel):
    lead_ids: list[int]
    agent_id: Optional[int] = None
    assigned_user_id: Optional[int] = None
    batch_id: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    notes: Optional[str] = None
    dialer_source: str = "batch_dialer"


class CallOutcomeApplyRequest(SQLModel):
    interaction_id: Optional[int] = None
    raw_status: Optional[str] = None
    transcript: Optional[str] = None


class LeadOptOutRequest(SQLModel):
    reason: Optional[str] = None


class VoiceAgentCreate(SQLModel):
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    stt_provider: Optional[str] = None
    llm_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    telephony_engine: Optional[str] = None


class VoiceAgentUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    agent_type: Optional[str] = None


class VoiceAgentRuntimeUpdate(SQLModel):
    stt_provider: Optional[str] = None
    llm_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    telephony_engine: Optional[str] = None
    voice_preset_id: Optional[int] = None
    language: Optional[str] = None
    ai_verbosity: Optional[str] = None
    max_call_duration_seconds: Optional[int] = None
    silence_reengage_seconds: Optional[int] = None
    business_hours_json: Optional[dict] = None
    runtime_json: Optional[dict] = None


class VoiceAgentPromptCreate(SQLModel):
    name: str = "Prompt"
    system_prompt: str
    instructions: Optional[str] = None
    publish: bool = True
    traffic_split: Optional[int] = 0


class VoiceAgentExecutionEventCreate(SQLModel):
    agent_id: Optional[int] = None
    interaction_id: Optional[int] = None
    call_task_id: Optional[int] = None
    event_type: str
    provider: Optional[str] = None
    summary: Optional[str] = None
    payload: dict = {}


class VoiceAgentExtractionTemplateUpsert(SQLModel):
    name: str
    instructions: Optional[str] = None
    extraction_schema: dict = {}
    is_active: bool = True


class VoiceAgentToolUpsert(SQLModel):
    name: str
    description: Optional[str] = None
    tool_type: str = "custom_http"
    input_schema_json: dict = {}
    http_method: Optional[str] = None
    url: Optional[str] = None
    headers_json: Optional[dict] = None
    body_template: Optional[str] = None
    is_active: bool = True


class VoiceAgentGraphUpdate(SQLModel):
    graph_json: dict = {}
    is_enabled: bool = False

class Disposition(SQLModel, table=True):
    """Structured outcome classification template for voice calls.
    Each agent can have multiple dispositions with attached instructions
    that the LLM uses to classify the call outcome."""
    __tablename__ = "dispositions"
    __table_args__ = (
        UniqueConstraint("agent_id", "key", name="uq_dispositions_agent_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_id: int = Field(foreign_key="voice_agents.id", index=True)
    key: str = Field(max_length=80)
    label: str = Field(max_length=150)
    description: Optional[str] = None
    instructions: Optional[str] = None  # LLM guidance for classifying this outcome
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class DispositionResult(SQLModel, table=True):
    """One disposition assignment per call — the actual outcome class."""
    __tablename__ = "disposition_results"
    __table_args__ = (
        Index("ix_disposition_results_interaction", "interaction_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    disposition_id: int = Field(foreign_key="dispositions.id", index=True)
    agent_id: int = Field(foreign_key="voice_agents.id", index=True)
    confidence: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(5, 2), nullable=False))
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class MarkTrackingRecord(SQLModel, table=True):
    """Tracks TTS audio delivery — one row per mark sent to the telephony provider.
    Used for verifying that every sentence reached the customer's ear."""
    __tablename__ = "mark_tracking_records"
    __table_args__ = (
        Index("ix_mark_tracking_interaction_seq", "interaction_id", "sequence_number"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    sequence_number: int = Field(default=0)
    sentence: Optional[str] = None
    length_chars: int = Field(default=0)
    length_bytes: int = Field(default=0)
    enqueued_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    delivered_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    provider_mark_sid: Optional[str] = Field(default=None, max_length=200)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class CallAudioEvent(SQLModel, table=True):
    """External events injected into an active call — interruptions,
    forced prompts, hold music triggers, etc."""
    __tablename__ = "call_audio_events"
    __table_args__ = (
        Index("ix_call_audio_events_interaction_created", "interaction_id", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    interaction_id: int = Field(foreign_key="interactions.id", index=True)
    event_type: str = Field(max_length=80)     # "interrupt" | "say" | "hold_music" | "custom_action"
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="pending", max_length=30)  # pending | queued | delivered | failed
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    processed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

class AgentTemplate(SQLModel, table=True):
    """Pre-built agent configuration templates that can be cloned
    and customised per company. Stored in the platform library."""
    __tablename__ = "agent_templates"
    __table_args__ = (
        UniqueConstraint("key", name="uq_agent_templates_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True, max_length=80)
    name: str = Field(max_length=150)
    description: Optional[str] = None
    category: str = Field(default="general", max_length=60)  # sales | support | qualification | followup
    industry: Optional[str] = Field(default=None, max_length=80)
    is_public: bool = Field(default=True)
    is_active: bool = Field(default=True)
    version: int = Field(default=1)
    config_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    system_prompt: str = Field(default="")
    instructions: Optional[str] = None
    tags: list = Field(default_factory=list, sa_column=Column(JSON, nullable=True))
    usage_count: int = Field(default=0)     # how many companies have deployed this
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class ProviderCredential(SQLModel, table=True):
    """Per-company provider API key management for ASR/TTS/LLM/telephony.
    Stored encrypted; exposed via masked read endpoints."""
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("company_id", "provider", "key_name", name="uq_provider_creds_company_provider_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    provider: str = Field(max_length=50)     # deepgram | cartesia | mistral | openai | elevenlabs | twilio | plivo | exotel
    key_name: str = Field(max_length=80)    # API_KEY | API_SECRET | ACCOUNT_SID | VOICE_ID
    value_encrypted: str = Field(sa_column=Column(Text, nullable=False))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class CostRecord(SQLModel, table=True):
    """Per-interaction cost breakdown for calls.
    One row per call with estimated cost for each provider used."""
    __tablename__ = "cost_records"
    __table_args__ = (
        Index("ix_cost_records_interaction", "interaction_id"),
        Index("ix_cost_records_company_created", "company_id", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    agent_id: Optional[int] = Field(default=None, foreign_key="voice_agents.id", index=True)
    call_task_id: Optional[int] = Field(default=None, foreign_key="call_tasks.id", index=True)
    duration_seconds: int = Field(default=0)
    stt_cost: Decimal = Field(default=Decimal("0.000000"), sa_column=Column(Numeric(12, 8), nullable=False))
    llm_cost: Decimal = Field(default=Decimal("0.000000"), sa_column=Column(Numeric(12, 8), nullable=False))
    tts_cost: Decimal = Field(default=Decimal("0.000000"), sa_column=Column(Numeric(12, 8), nullable=False))
    telephony_cost: Decimal = Field(default=Decimal("0.000000"), sa_column=Column(Numeric(12, 8), nullable=False))
    total_cost: Decimal = Field(default=Decimal("0.000000"), sa_column=Column(Numeric(12, 8), nullable=False))
    currency: str = Field(default="USD", max_length=10)
    stt_provider: Optional[str] = Field(default=None, max_length=50)
    llm_provider: Optional[str] = Field(default=None, max_length=50)
    tts_provider: Optional[str] = Field(default=None, max_length=50)
    telephony_provider: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class ProviderRate(SQLModel, table=True):
    """Custom provider rates configured per company (Option A)."""
    __tablename__ = "provider_rates"
    __table_args__ = (
        Index("ix_provider_rates_company_provider", "company_id", "category", "provider"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    category: str = Field(max_length=50, index=True)  # "stt", "llm", "tts", "telephony"
    provider: str = Field(max_length=50, index=True)  # "deepgram", "openai", "cartesia", "twilio", etc.
    model_or_voice: Optional[str] = Field(default=None, max_length=100)  # E.g. "aura-asteria-en"
    rate_per_second: Decimal = Field(default=Decimal("0.00000000"), sa_column=Column(Numeric(12, 8), nullable=False))
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class ProviderRateCreate(SQLModel):
    category: str = Field(max_length=50)
    provider: str = Field(max_length=50)
    model_or_voice: Optional[str] = Field(default=None, max_length=100)
    rate_per_second: Decimal
    is_active: bool = True


class ProviderRateUpdate(SQLModel):
    rate_per_second: Optional[Decimal] = None
    is_active: Optional[bool] = None

class DispositionCreate(SQLModel):
    key: str = Field(max_length=80)
    label: str = Field(max_length=150)
    description: Optional[str] = None
    instructions: Optional[str] = None
    is_active: bool = True


class DispositionUpdate(SQLModel):
    label: Optional[str] = None
    description: Optional[str] = None
    instructions: Optional[str] = None
    is_active: Optional[bool] = None


class DispositionResultCreate(SQLModel):
    interaction_id: int
    disposition_id: int
    confidence: Decimal = Decimal("0.00")
    notes: Optional[str] = None


class DispositionTestRequest(SQLModel):
    """Test a disposition against a transcript to preview classification."""
    transcript: str
    disposition_key: str


class EventInjectionRequest(SQLModel):
    """Inject an event into an active call."""
    interaction_id: int
    event_type: str = Field(max_length=80)
    payload: dict = {}


class MarkSummaryRow(SQLModel):
    sequence_number: int
    sentence: str
    delivered: bool
    enqueued_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    latency_ms: Optional[int] = None

class AgentTemplateCreate(SQLModel):
    key: str = Field(max_length=80)
    name: str = Field(max_length=150)
    description: Optional[str] = None
    category: str = "general"
    industry: Optional[str] = None
    is_public: bool = True
    config_json: dict = {}
    system_prompt: str = ""
    instructions: Optional[str] = None
    tags: list = []


class AgentTemplateUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    industry: Optional[str] = None
    is_public: Optional[bool] = None
    is_active: Optional[bool] = None
    config_json: Optional[dict] = None
    system_prompt: Optional[str] = None
    instructions: Optional[str] = None
    tags: Optional[list] = None


class ProviderCredentialCreate(SQLModel):
    provider: str = Field(max_length=50)
    key_name: str = Field(max_length=80)
    value: str = Field(max_length=1000)
    is_active: bool = True


class ProviderCredentialUpdate(SQLModel):
    value: Optional[str] = None
    is_active: Optional[bool] = None


class ProviderCredentialRead(SQLModel):
    id: int
    provider: str
    key_name: str
    value_masked: str
    is_active: bool
    updated_at: Optional[datetime] = None


class CostQueryParams(SQLModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    agent_id: Optional[int] = None


class CostBreakdownRow(SQLModel):
    date: str
    total_calls: int = 0
    total_minutes: float = 0.0
    stt_cost: float = 0.0
    llm_cost: float = 0.0
    tts_cost: float = 0.0
    telephony_cost: float = 0.0
    total_cost: float = 0.0
    cost_per_minute: float = 0.0

class Contact(AuditMixin, table=True):
    """Known person at an Account. Separate from Lead (prospect)."""
    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("company_id", "account_id", "email", name="uq_contacts_company_account_email"),
        Index("ix_contacts_company_account", "company_id", "account_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    name: str = Field(max_length=200)
    email: Optional[str] = Field(default=None, max_length=255, index=True)
    phone: Optional[str] = Field(default=None, max_length=30)
    designation: Optional[str] = Field(default=None, max_length=150)
    department: Optional[str] = Field(default=None, max_length=100)
    is_primary: bool = Field(default=False)
    preferred_language: Optional[str] = Field(default="en", max_length=10)
    notes: Optional[str] = None
    is_active: bool = Field(default=True)


class Order(AuditMixin, table=True):
    """
    Created from an accepted Quote. Triggers fulfillment chain.

    Status lifecycle:
      pending → confirmed → processing → shipped | ready_for_install
      → delivered | installed → closed | cancelled
    """
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("company_id", "order_number", name="uq_orders_company_number"),
        Index("ix_orders_company_status", "company_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id", index=True)
    quote_id: Optional[int] = Field(default=None, foreign_key="quotes.id", index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    order_number: str = Field(max_length=50, index=True)
    status: str = Field(default="pending", max_length=30)
    currency: str = Field(default="INR", max_length=10)
    subtotal: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    discount_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    tax_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    total_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    delivery_address: Optional[str] = Field(default=None, max_length=500)
    delivery_city: Optional[str] = Field(default=None, max_length=100)
    delivery_state: Optional[str] = Field(default=None, max_length=100)
    delivery_pincode: Optional[str] = Field(default=None, max_length=20)
    expected_delivery_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    confirmed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    shipped_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    delivered_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    cancelled_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    cancellation_reason: Optional[str] = None
    notes: Optional[str] = None
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class OrderItem(AuditMixin, table=True):
    __tablename__ = "order_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="orders.id", index=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    product_id: Optional[int] = Field(default=None, foreign_key="products.id", index=True)
    product_name_snapshot: str = Field(max_length=200)
    sku_snapshot: Optional[str] = Field(default=None, max_length=100)
    quantity: int = Field(default=1)
    unit_price: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    discount_percent: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(5, 2), nullable=False))
    line_total: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    serial_numbers: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    notes: Optional[str] = None


class Invoice(AuditMixin, table=True):
    """
    Generated from an Order. Sent to customer; tracks payment.

    Status lifecycle:
      draft → sent → partially_paid → paid → overdue → cancelled | written_off
    """
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("company_id", "invoice_number", name="uq_invoices_company_number"),
        Index("ix_invoices_company_status_due", "company_id", "status", "due_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    order_id: Optional[int] = Field(default=None, foreign_key="orders.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id", index=True)
    owner_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    invoice_number: str = Field(max_length=50, index=True)
    status: str = Field(default="draft", max_length=30)
    currency: str = Field(default="INR", max_length=10)
    subtotal: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    discount_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    tax_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    total_amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    amount_paid: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    amount_due: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    due_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    sent_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    paid_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    overdue_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    payment_link: Optional[str] = Field(default=None, max_length=500)
    pdf_path: Optional[str] = None
    gst_number: Optional[str] = Field(default=None, max_length=50)
    billing_address: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None
    requires_approval: bool = Field(default=False)


class InvoiceItem(AuditMixin, table=True):
    __tablename__ = "invoice_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    invoice_id: int = Field(foreign_key="invoices.id", index=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    order_item_id: Optional[int] = Field(default=None, foreign_key="order_items.id", index=True)
    description: str = Field(max_length=300)
    quantity: int = Field(default=1)
    unit_price: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    tax_rate: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(5, 2), nullable=False))
    line_total: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    hsn_code: Optional[str] = Field(default=None, max_length=20)


class Payment(AuditMixin, table=True):
    """
    Records a payment received against an Invoice.

    Status: pending → captured → failed | refunded
    """
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_company_invoice", "company_id", "invoice_id"),
        UniqueConstraint("company_id", "reference_number", name="uq_payments_company_reference"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    invoice_id: int = Field(foreign_key="invoices.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    amount: Decimal = Field(default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False))
    currency: str = Field(default="INR", max_length=10)
    status: str = Field(default="pending", max_length=30)
    payment_method: str = Field(default="bank_transfer", max_length=50)
    reference_number: Optional[str] = Field(default=None, max_length=200, index=True)
    gateway: Optional[str] = Field(default=None, max_length=50)
    gateway_transaction_id: Optional[str] = Field(default=None, max_length=200, index=True)
    captured_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    refunded_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    refund_reason: Optional[str] = None
    notes: Optional[str] = None
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))

class ServiceTicket(AuditMixin, table=True):
    """
    Customer service/support ticket.

    Status lifecycle:
      open → in_progress → pending_customer | pending_parts → resolved → closed
      Any status → escalated (SLA breach)
    """
    __tablename__ = "service_tickets"
    __table_args__ = (
        UniqueConstraint("company_id", "ticket_number", name="uq_tickets_company_number"),
        Index("ix_tickets_company_status_priority", "company_id", "status", "priority"),
        Index("ix_tickets_company_sla_due", "company_id", "sla_due_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    account_id: Optional[int] = Field(default=None, foreign_key="accounts.id", index=True)
    order_id: Optional[int] = Field(default=None, foreign_key="orders.id", index=True)
    assignee_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    ticket_number: str = Field(max_length=50, index=True)
    title: str = Field(max_length=300)
    description: Optional[str] = None
    status: str = Field(default="open", max_length=30)
    priority: str = Field(default="medium", max_length=20)  # low | medium | high | critical
    category: str = Field(default="general", max_length=50)  # installation | maintenance | billing | general
    channel: str = Field(default="manual", max_length=30)  # manual | call | email | whatsapp
    source_interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    sla_hours: int = Field(default=24)
    sla_due_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    first_response_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    resolved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    closed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    csat_score: Optional[int] = None  # 1-5
    csat_comment: Optional[str] = None
    tags: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))


class TicketComment(AuditMixin, table=True):
    __tablename__ = "ticket_comments"
    __table_args__ = (
        Index("ix_ticket_comments_ticket", "ticket_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    ticket_id: int = Field(foreign_key="service_tickets.id", index=True)
    author_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    body: str
    is_internal: bool = Field(default=False)
    attachments_json: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))


class InstallationJob(AuditMixin, table=True):
    """
    Field installation task linked to an Order.

    Status lifecycle:
      scheduled → prerequisite_check → assigned → in_progress → completed | failed
    """
    __tablename__ = "installation_jobs"
    __table_args__ = (
        UniqueConstraint("company_id", "job_number", name="uq_install_jobs_company_number"),
        Index("ix_install_jobs_company_status", "company_id", "status"),
        Index("ix_install_jobs_scheduled_at", "company_id", "scheduled_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    order_id: int = Field(foreign_key="orders.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    ticket_id: Optional[int] = Field(default=None, foreign_key="service_tickets.id", index=True)
    assigned_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    job_number: str = Field(max_length=50, index=True)
    status: str = Field(default="scheduled", max_length=30)
    scheduled_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    started_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    installation_address: Optional[str] = Field(default=None, max_length=500)
    checklist_json: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    prerequisites_met: bool = Field(default=False)
    completion_notes: Optional[str] = None
    customer_signature_url: Optional[str] = None
    photos_json: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))
    csat_score: Optional[int] = None

class ConsentRecord(SQLModel, table=True):
    """
    Per-lead per-channel consent tracking.
    Required before sending regulated comms (WhatsApp, calls, email).
    """
    __tablename__ = "consent_records"
    __table_args__ = (
        UniqueConstraint("company_id", "lead_id", "channel", name="uq_consent_company_lead_channel"),
        Index("ix_consent_company_lead", "company_id", "lead_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    channel: str = Field(max_length=50)  # call | email | whatsapp | sms
    status: str = Field(default="pending", max_length=30)  # pending | granted | revoked | expired
    granted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    revoked_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    source: str = Field(default="explicit", max_length=50)  # explicit | implied | imported
    source_interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class ApproverRoute(AuditMixin, table=True):
    """
    Rule-based approver assignment. Evaluated when AgentApproval is created.
    First matching rule assigns the approver(s); fallback = any admin.

    Condition keys (action_type, amount_gt, amount_lte, discount_gt, risk_level, category)
    are AND-combined.
    """
    __tablename__ = "approver_routes"
    __table_args__ = (
        Index("ix_approver_routes_company_active_priority", "company_id", "is_active", "priority"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    description: Optional[str] = None
    priority: int = Field(default=10)
    condition_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    approver_user_ids: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    sla_hours: int = Field(default=24)
    is_active: bool = Field(default=True)


class EscalationRule(AuditMixin, table=True):
    """
    Auto-escalates an approval when SLA is breached.
    Checked by the automation worker on each cycle.
    """
    __tablename__ = "escalation_rules"
    __table_args__ = (
        Index("ix_escalation_rules_company_active", "company_id", "is_active"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    trigger_after_hours: int = Field(default=24)
    escalate_to_user_ids: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    action_types: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(default=True)


class PolicyDecisionLog(SQLModel, table=True):
    """
    Persisted result of PolicyDecision evaluation.
    Every automated action evaluated through the policy engine gets a row.

    decision: auto_execute | needs_approval | blocked
    """
    __tablename__ = "policy_decision_logs"
    __table_args__ = (
        Index("ix_policy_decision_logs_company_created", "company_id", "created_at"),
        Index("ix_policy_decision_logs_entity", "entity_type", "entity_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    entity_type: str = Field(max_length=80)   # order | invoice | quote | agent_task
    entity_id: Optional[int] = Field(default=None, index=True)
    action_type: str = Field(max_length=100)
    decision: str = Field(max_length=30)      # auto_execute | needs_approval | blocked
    reasons: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    risk_score: Optional[Decimal] = Field(default=None, sa_column=Column(Numeric(5, 2), nullable=True))
    required_approvers: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    context_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    actor_agent: Optional[str] = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))

class EventStore(SQLModel, table=True):
    """
    Immutable append-only event log with correlation IDs.
    Every significant domain state change emits an event here.
    Never updated; only inserted.

    event_type examples:
      lead.stage_changed | quote.accepted | order.confirmed | invoice.sent
      payment.captured | ticket.opened | ticket.resolved | install.completed
    """
    __tablename__ = "event_store"
    __table_args__ = (
        Index("ix_event_store_company_type_created", "company_id", "event_type", "created_at"),
        Index("ix_event_store_aggregate", "aggregate_type", "aggregate_id"),
        Index("ix_event_store_correlation", "correlation_id"),
        Index("ix_event_store_causation", "causation_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    event_type: str = Field(max_length=120, index=True)
    aggregate_type: str = Field(max_length=80)    # lead | quote | order | invoice | ticket
    aggregate_id: int = Field(index=True)
    correlation_id: str = Field(max_length=64, index=True)    # ties events from same user action
    causation_id: Optional[str] = Field(default=None, max_length=64, index=True)  # event that caused this
    version: int = Field(default=1)               # per-aggregate sequence number
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    actor_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    actor_agent: Optional[str] = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))


class WorkflowDefinition(AuditMixin, table=True):
    """Reusable workflow template (e.g. 'post_sale_onboarding', 'service_ticket_flow')."""
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        UniqueConstraint("company_id", "key", name="uq_workflow_definitions_company_key"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    key: str = Field(max_length=100)
    name: str = Field(max_length=200)
    description: Optional[str] = None
    steps_json: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    trigger_events: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    is_active: bool = Field(default=True)
    version: int = Field(default=1)


class WorkflowInstance(SQLModel, table=True):
    __tablename__ = "workflow_instances"
    __table_args__ = (
        Index("ix_workflow_instances_company_status", "company_id", "status"),
        Index("ix_workflow_instances_entity", "entity_type", "entity_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    definition_id: int = Field(foreign_key="workflow_definitions.id", index=True)
    entity_type: str = Field(max_length=80)
    entity_id: int = Field(index=True)
    status: str = Field(default="running", max_length=30)
    current_step_index: int = Field(default=0)
    context_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    started_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    error: Optional[str] = None


class WorkflowStep(SQLModel, table=True):
    """Individual step execution record within a WorkflowInstance."""
    __tablename__ = "workflow_steps"
    __table_args__ = (
        Index("ix_workflow_steps_instance", "instance_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    instance_id: int = Field(foreign_key="workflow_instances.id", index=True)
    step_index: int = Field(default=0)
    step_key: str = Field(max_length=100)
    status: str = Field(default="pending", max_length=30)  # pending | running | done | failed | skipped
    input_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    output_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    error: Optional[str] = None
    attempts: int = Field(default=0)
    run_after: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    started_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

class TelephonyProviderHealth(SQLModel, table=True):
    __tablename__ = "telephony_provider_health"
    __table_args__ = (
        UniqueConstraint("company_id", "provider", name="uq_telephony_provider_health"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    provider: str = Field(max_length=50)   # twilio | exotel | enablex | plivo | vobiz
    is_healthy: bool = Field(default=True)
    success_count: int = Field(default=0)
    failure_count: int = Field(default=0)
    consecutive_failures: int = Field(default=0)
    last_success_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_failure_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_error: Optional[str] = Field(default=None, max_length=500)
    updated_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))

class OrderCreate(SQLModel):
    lead_id: int
    account_id: Optional[int] = None
    quote_id: Optional[int] = None
    currency: str = "INR"
    delivery_address: Optional[str] = None
    delivery_city: Optional[str] = None
    delivery_state: Optional[str] = None
    delivery_pincode: Optional[str] = None
    expected_delivery_at: Optional[datetime] = None
    notes: Optional[str] = None


class OrderStatusUpdate(SQLModel):
    status: str
    notes: Optional[str] = None


class InvoiceCreate(SQLModel):
    order_id: Optional[int] = None
    lead_id: int
    account_id: Optional[int] = None
    currency: str = "INR"
    due_date: Optional[datetime] = None
    gst_number: Optional[str] = None
    billing_address: Optional[str] = None
    notes: Optional[str] = None
    requires_approval: bool = False


class InvoiceSendRequest(SQLModel):
    send_via: list = []  # ["email", "whatsapp"]


class PaymentCreate(SQLModel):
    invoice_id: int
    lead_id: int
    amount: Decimal
    payment_method: str = "bank_transfer"
    reference_number: Optional[str] = None
    gateway: Optional[str] = None
    notes: Optional[str] = None


class ServiceTicketCreate(SQLModel):
    lead_id: Optional[int] = None
    account_id: Optional[int] = None
    order_id: Optional[int] = None
    title: str
    description: Optional[str] = None
    priority: str = "medium"
    category: str = "general"
    channel: str = "manual"
    sla_hours: int = 24


class TicketCommentCreate(SQLModel):
    body: str
    is_internal: bool = False


class InstallationJobCreate(SQLModel):
    order_id: int
    lead_id: int
    ticket_id: Optional[int] = None
    scheduled_at: Optional[datetime] = None
    installation_address: Optional[str] = None
    checklist_json: Optional[list] = None


class ContactCreate(SQLModel):
    account_id: Optional[int] = None
    lead_id: Optional[int] = None
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    designation: Optional[str] = None
    department: Optional[str] = None
    is_primary: bool = False


class ApproverRouteCreate(SQLModel):
    name: str
    description: Optional[str] = None
    priority: int = 10
    condition_json: dict = {}
    approver_user_ids: list = []
    sla_hours: int = 24


class EscalationRuleCreate(SQLModel):
    name: str
    trigger_after_hours: int = 24
    escalate_to_user_ids: list = []
    action_types: list = []


class ToolCallLog(SQLModel, table=True):
    __tablename__ = "tool_call_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    interaction_id: Optional[int] = Field(default=None, foreign_key="interactions.id", index=True)
    tool_name: str = Field(max_length=100, index=True)
    status: str = Field(default="success", max_length=20)  # success | error | timeout
    duration_ms: int = Field(default=0)
    error_message: Optional[str] = Field(default=None, max_length=500)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


# ---------------------------------------------------------------------------
# Agent Infrastructure — Action Ledger, Object Lock, Serial Registry,
# Tally Staging, KPI Events
# ---------------------------------------------------------------------------

class ActionLedger(SQLModel, table=True):
    """Permanent immutable log of every atomic action any agent ever takes.

    Written once per agent action — whether proposed, approved, rejected,
    executed, or failed. Never updated after creation; status transitions
    produce new rows so the full history is always preserved.

    Autonomy tiers:
      A1 — propose only: row created with status="proposed", waits for approval
      A2 — supervised: row created with status="proposed", executed on approval
      A3 — bounded-autonomous: row created with status="auto_executed" directly

    This table is the single source of truth for the monthly agent-assurance
    review and the basis for promoting agents from A1 → A2 → A3.
    """
    __tablename__ = "action_ledger"
    __table_args__ = (
        Index("ix_action_ledger_company_agent_created", "company_id", "agent_name", "created_at"),
        Index("ix_action_ledger_company_status", "company_id", "status"),
        Index("ix_action_ledger_entity", "company_id", "entity_type", "entity_id"),
        Index("ix_action_ledger_task", "agent_task_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)

    # What ran
    agent_name: str = Field(max_length=80, index=True)   # "f1_collections" | "p1_purchase" …
    action_type: str = Field(max_length=120)              # "send_dunning_whatsapp" | "create_po" …
    autonomy_level: str = Field(max_length=5)             # "A1" | "A2" | "A3"

    # Status lifecycle (immutable per row — new row per transition)
    # proposed → approved → executed
    # proposed → rejected
    # auto_executed (A3, no approval required)
    # failed (execution error after approval)
    status: str = Field(default="proposed", max_length=30)

    # What the agent saw and produced
    input_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    output_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    rationale: str = Field(default="")  # why the agent took this action

    # Links
    agent_task_id: Optional[int] = Field(default=None, foreign_key="agent_tasks.id", index=True)
    entity_type: Optional[str] = Field(default=None, max_length=80)   # "invoice" | "dealer" | "po"
    entity_id: Optional[int] = Field(default=None, index=True)         # DB id of the touched record

    # Approval
    approved_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    reviewer_note: Optional[str] = None

    # Execution outcome
    executed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    error: Optional[str] = None

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AgentObjectLock(SQLModel, table=True):
    """Distributed record-level lock preventing two agents from writing the same
    entity concurrently.

    An agent acquires the lock before touching a record, releases it after.
    Locks have a hard TTL (expires_at) so a crashed agent never starves others.
    The orchestrator checks this table before dispatching any A2/A3 action.
    """
    __tablename__ = "agent_object_locks"
    __table_args__ = (
        UniqueConstraint("company_id", "entity_type", "entity_id", name="uq_agent_object_locks_entity"),
        Index("ix_agent_object_locks_expires", "expires_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    entity_type: str = Field(max_length=80)   # "invoice" | "dealer" | "purchase_order" …
    entity_id: int                             # the DB id of the locked record
    locked_by_agent: str = Field(max_length=80)
    locked_by_task_id: Optional[int] = Field(default=None, foreign_key="agent_tasks.id", index=True)
    acquired_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )


class SerialRegistry(SQLModel, table=True):
    """Serial-level inventory tracking for serialized products.

    Every unit Yexis receives is registered here at GRN time.
    Supports perpetual, serial-accurate inventory and full chain-of-custody
    from goods-in through dispatch / demo / RMA / write-off.
    """
    __tablename__ = "serial_registry"
    __table_args__ = (
        UniqueConstraint("company_id", "serial_number", name="uq_serial_registry_company_serial"),
        Index("ix_serial_registry_company_status", "company_id", "status"),
        Index("ix_serial_registry_product", "company_id", "product_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    serial_number: str = Field(max_length=100, index=True)
    product_id: Optional[int] = Field(default=None, foreign_key="products.id", index=True)
    sku_snapshot: Optional[str] = Field(default=None, max_length=100)  # frozen at GRN time
    model_snapshot: Optional[str] = Field(default=None, max_length=200)

    # Provenance
    po_number: Optional[str] = Field(default=None, max_length=100)
    grn_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    vendor_name: Optional[str] = Field(default=None, max_length=200)

    # Current state
    # in_stock | allocated | dispatched | demo | sold | rma | written_off
    status: str = Field(default="in_stock", max_length=30, index=True)
    location: Optional[str] = Field(default=None, max_length=200)  # "godown_chennai" | "site_xyz"

    # Allocation / dispatch
    allocated_to_lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    dispatched_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    sold_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    notes: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class TallyStagingVoucher(SQLModel, table=True):
    """Staging area for Zoho Books transactions pending sync to Tally Prime.

    The F3 Books-Sync agent writes rows here after pulling the Zoho Books
    day-book. A human (accountant) reviews and approves in bulk via the
    Cowork approval console. The Tally Gateway then posts approved rows and
    writes back tally_voucher_id on success.

    This decouples Zoho Books from Tally and gives full auditability over
    what was posted, when, and by whom — critical for statutory compliance.
    """
    __tablename__ = "tally_staging_vouchers"
    __table_args__ = (
        UniqueConstraint("company_id", "zoho_books_ref", name="uq_tally_staging_zoho_ref"),
        Index("ix_tally_staging_company_status", "company_id", "status"),
        Index("ix_tally_staging_voucher_date", "company_id", "voucher_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)

    # Source
    zoho_books_ref: str = Field(max_length=100, index=True)  # Zoho Books txn ID or number
    # sales_invoice | purchase_invoice | payment | receipt | journal | contra | credit_note | debit_note
    voucher_type: str = Field(max_length=50)
    voucher_date: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    party_name: Optional[str] = Field(default=None, max_length=200)  # Tally ledger name
    narration: Optional[str] = Field(default=None, max_length=500)
    amount: Optional[str] = Field(default=None, max_length=30)  # stored as string to preserve exact decimal

    # Tally mapping
    mapped_ledger: Optional[str] = Field(default=None, max_length=200)
    voucher_data_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))  # full Tally XML payload

    # Lifecycle
    # staged | pending_approval | approved | posting | posted | failed | rejected | skipped
    status: str = Field(default="staged", max_length=30)

    # Approval
    approved_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    approved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    rejection_reason: Optional[str] = None

    # Tally post result
    tally_voucher_id: Optional[str] = Field(default=None, max_length=100)  # returned by Tally on success
    posted_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    error: Optional[str] = None
    retry_count: int = Field(default=0)

    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AgentKpiEvent(SQLModel, table=True):
    """One measurable outcome produced by an agent, recorded at execution time.

    Aggregated by the D1 Dashboard agent into KPI snapshots.
    Also used to track agent performance for the monthly assurance review
    and to gate autonomy promotion (e.g., F2 must hit 97% claim accuracy
    before being promoted from A1 to A2).
    """
    __tablename__ = "agent_kpi_events"
    __table_args__ = (
        Index("ix_agent_kpi_events_company_agent_metric", "company_id", "agent_name", "metric_name"),
        Index("ix_agent_kpi_events_period", "company_id", "period_date"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    agent_name: str = Field(max_length=80, index=True)
    # e.g. "dso_days" | "collection_hit_rate" | "po_cycle_time_hours"
    #      "scheme_claim_accuracy" | "grn_serial_capture_accuracy" | "tally_sync_drift_inr"
    metric_name: str = Field(max_length=120, index=True)
    metric_value: Optional[str] = Field(default=None, max_length=50)  # stored as string; parse as Decimal/float downstream
    period_date: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    entity_type: Optional[str] = Field(default=None, max_length=80)   # "dealer" | "branch" | "sku"
    entity_id: Optional[int] = Field(default=None, index=True)
    action_ledger_id: Optional[int] = Field(default=None, foreign_key="action_ledger.id", index=True)
    metadata_json: Optional[dict] = Field(default=None, sa_column=Column(JSON, nullable=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class VendorScheme(SQLModel, table=True):
    """Scheme definition entered by the finance team from a vendor's scheme PDF.

    Vendors run promotional incentive schemes every month/quarter:
      volume_incentive   — sell N+ units, earn rate_per_unit on all qualifying units
      model_incentive    — sell specific SKUs, earn flat rate per unit
      display_incentive  — maintain display units at dealers, flat monthly amount
      mdf                — market development fund, flat amount for territory promotions

    incentive_rules JSON shape (interpreted by f2_scheme_claims agent):
      volume_incentive : [{"min_qty": 0, "max_qty": 49, "rate_per_unit": 300},
                          {"min_qty": 50, "max_qty": null, "rate_per_unit": 500}]
      model_incentive  : {"rate_per_unit": 800}
      display_incentive: {"flat_amount": 25000}
      mdf              : {"flat_amount": 50000}
    """
    __tablename__ = "vendor_schemes"
    __table_args__ = (
        UniqueConstraint("company_id", "scheme_code", "period_start",
                         name="uq_vendor_scheme_code_period"),
        Index("ix_vendor_schemes_company_status", "company_id", "status"),
        Index("ix_vendor_schemes_period", "company_id", "period_start", "period_end"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    scheme_code: str = Field(max_length=100, index=True)
    scheme_name: str = Field(max_length=300)
    # volume_incentive | model_incentive | display_incentive | mdf
    scheme_type: str = Field(max_length=50)
    period_start: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    period_end: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    submission_deadline: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    eligible_brands: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    eligible_categories: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    eligible_skus: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    min_quantity: int = Field(default=0)
    incentive_rules: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    status: str = Field(default="active", max_length=30)
    source_document_path: Optional[str] = Field(default=None, max_length=500)
    notes: Optional[str] = None
    created_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class SchemeClaim(SQLModel, table=True):
    """A drafted or submitted incentive claim against one SamsungScheme.

    Status lifecycle:
      draft → proposed → approved → submitted → acknowledged → settled | rejected | disputed
    """
    __tablename__ = "scheme_claims"
    __table_args__ = (
        UniqueConstraint("company_id", "scheme_id", "claim_period_start",
                         name="uq_scheme_claim_scheme_period"),
        Index("ix_scheme_claims_company_status", "company_id", "status"),
        Index("ix_scheme_claims_scheme", "scheme_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    scheme_id: int = Field(foreign_key="vendor_schemes.id", index=True)
    claim_period_start: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    claim_period_end: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    total_qualifying_units: int = Field(default=0)
    total_claimed_inr: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(14, 2), nullable=False)
    )
    settled_amount_inr: Optional[Decimal] = Field(
        default=None, sa_column=Column(Numeric(14, 2), nullable=True)
    )
    variance_inr: Optional[Decimal] = Field(
        default=None, sa_column=Column(Numeric(14, 2), nullable=True)
    )
    # abs(settled - claimed) / claimed * 100; drives scheme_claim_accuracy KPI
    accuracy_pct: Optional[Decimal] = Field(
        default=None, sa_column=Column(Numeric(6, 2), nullable=True)
    )
    status: str = Field(default="draft", max_length=30)
    action_ledger_id: Optional[int] = Field(default=None, foreign_key="action_ledger.id", index=True)
    agent_task_id: Optional[int] = Field(default=None, foreign_key="agent_tasks.id", index=True)
    approved_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    approved_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    reviewer_note: Optional[str] = None
    submission_ref: Optional[str] = Field(default=None, max_length=200)
    submitted_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    settled_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    rejection_reason: Optional[str] = None
    claim_workings: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class SchemeClaimLine(SQLModel, table=True):
    """One qualifying invoice×product line in a SchemeClaim.

    Finance Manager inspects these to verify agent workings before approving.
    """
    __tablename__ = "scheme_claim_lines"
    __table_args__ = (
        Index("ix_scheme_claim_lines_claim", "claim_id"),
        Index("ix_scheme_claim_lines_invoice", "invoice_id"),
        Index("ix_scheme_claim_lines_product", "product_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    claim_id: int = Field(foreign_key="scheme_claims.id", index=True)
    invoice_id: int = Field(foreign_key="invoices.id", index=True)
    product_id: Optional[int] = Field(default=None, foreign_key="products.id", index=True)
    lead_id: int = Field(foreign_key="leads.id", index=True)
    sku_snapshot: Optional[str] = Field(default=None, max_length=100)
    product_name_snapshot: Optional[str] = Field(default=None, max_length=200)
    invoice_number: str = Field(max_length=50)
    invoice_date: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    quantity: int = Field(default=0)
    rate_per_unit: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(10, 2), nullable=False)
    )
    line_amount: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False)
    )
    serial_numbers: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


# ---------------------------------------------------------------------------
# Purchase Suite — P1 Indent / P2 PO / P3 GRN
# ---------------------------------------------------------------------------

class PurchaseIndent(SQLModel, table=True):
    """Demand signal generated by P1; becomes a PO once approved.

    Status: draft → proposed → approved → po_raised → cancelled
    """
    __tablename__ = "purchase_indents"
    __table_args__ = (
        UniqueConstraint("company_id", "indent_number", name="uq_purchase_indent_number"),
        Index("ix_purchase_indents_company_status", "company_id", "status"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    indent_number: str = Field(max_length=50, index=True)
    status: str = Field(default="draft", max_length=30)
    total_value_inr: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(14, 2), nullable=False)
    )
    autonomy_level: str = Field(default="A2", max_length=5)
    action_ledger_id: Optional[int] = Field(default=None, foreign_key="action_ledger.id", index=True)
    agent_task_id: Optional[int] = Field(default=None, foreign_key="agent_tasks.id", index=True)
    approved_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    approved_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    notes: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class PurchaseIndentLine(SQLModel, table=True):
    """One product line in a PurchaseIndent."""
    __tablename__ = "purchase_indent_lines"
    __table_args__ = (
        Index("ix_purchase_indent_lines_indent", "indent_id"),
        Index("ix_purchase_indent_lines_product", "product_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    indent_id: int = Field(foreign_key="purchase_indents.id", index=True)
    product_id: int = Field(foreign_key="products.id", index=True)
    sku_snapshot: Optional[str] = Field(default=None, max_length=100)
    product_name_snapshot: str = Field(max_length=200)
    current_stock: int = Field(default=0)
    reorder_level: int = Field(default=0)
    quantity_to_order: int = Field(default=0)
    unit_cost: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False)
    )
    line_total: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(14, 2), nullable=False)
    )
    required_by: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class PurchaseOrder(SQLModel, table=True):
    """Formal PO raised to a vendor after indent is approved.

    Status: draft → sent → acknowledged → partial_delivery → delivered | cancelled
    """
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("company_id", "po_number", name="uq_purchase_order_number"),
        Index("ix_purchase_orders_company_status", "company_id", "status"),
        Index("ix_purchase_orders_indent", "indent_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    po_number: str = Field(max_length=50, index=True)
    indent_id: Optional[int] = Field(default=None, foreign_key="purchase_indents.id", index=True)
    vendor_name: str = Field(default="", max_length=200)
    vendor_contact_email: Optional[str] = Field(default=None, max_length=200)
    status: str = Field(default="draft", max_length=30)
    total_value_inr: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(14, 2), nullable=False)
    )
    expected_delivery_date: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    sent_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    acknowledged_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    zoho_po_id: Optional[str] = Field(default=None, max_length=100)
    action_ledger_id: Optional[int] = Field(default=None, foreign_key="action_ledger.id", index=True)
    agent_task_id: Optional[int] = Field(default=None, foreign_key="agent_tasks.id", index=True)
    notes: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class PurchaseOrderLine(SQLModel, table=True):
    """One SKU line in a PurchaseOrder."""
    __tablename__ = "purchase_order_lines"
    __table_args__ = (
        Index("ix_po_lines_po", "po_id"),
        Index("ix_po_lines_product", "product_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    po_id: int = Field(foreign_key="purchase_orders.id", index=True)
    product_id: Optional[int] = Field(default=None, foreign_key="products.id", index=True)
    sku_snapshot: Optional[str] = Field(default=None, max_length=100)
    product_name_snapshot: str = Field(max_length=200)
    quantity_ordered: int = Field(default=0)
    quantity_received: int = Field(default=0)
    unit_cost: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False)
    )
    line_total: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(14, 2), nullable=False)
    )


class GoodsReceiptNote(SQLModel, table=True):
    """GRN header — records one physical delivery against a PO.

    Status: draft → verified → posted | discrepancy_flagged
    """
    __tablename__ = "goods_receipt_notes"
    __table_args__ = (
        UniqueConstraint("company_id", "grn_number", name="uq_grn_number"),
        Index("ix_grn_company_status", "company_id", "status"),
        Index("ix_grn_po", "po_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    grn_number: str = Field(max_length=50, index=True)
    po_id: int = Field(foreign_key="purchase_orders.id", index=True)
    received_by_user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    status: str = Field(default="draft", max_length=30)
    has_discrepancy: bool = Field(default=False)
    discrepancy_notes: Optional[str] = None
    action_ledger_id: Optional[int] = Field(default=None, foreign_key="action_ledger.id", index=True)
    agent_task_id: Optional[int] = Field(default=None, foreign_key="agent_tasks.id", index=True)
    vehicle_number: Optional[str] = Field(default=None, max_length=30)
    delivery_challan_number: Optional[str] = Field(default=None, max_length=100)
    received_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )
    updated_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )


class GRNLine(SQLModel, table=True):
    """One product line in a GRN — includes serial numbers and discrepancy detail."""
    __tablename__ = "grn_lines"
    __table_args__ = (
        Index("ix_grn_lines_grn", "grn_id"),
        Index("ix_grn_lines_product", "product_id"),
        Index("ix_grn_lines_po_line", "po_line_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    grn_id: int = Field(foreign_key="goods_receipt_notes.id", index=True)
    po_line_id: Optional[int] = Field(default=None, foreign_key="purchase_order_lines.id", index=True)
    product_id: Optional[int] = Field(default=None, foreign_key="products.id", index=True)
    sku_snapshot: Optional[str] = Field(default=None, max_length=100)
    product_name_snapshot: str = Field(max_length=200)
    quantity_ordered: int = Field(default=0)
    quantity_received: int = Field(default=0)
    quantity_accepted: int = Field(default=0)
    quantity_rejected: int = Field(default=0)
    discrepancy_type: Optional[str] = Field(default=None, max_length=50)
    # short_delivery | excess_delivery | model_mismatch | damage | serial_mismatch
    discrepancy_notes: Optional[str] = None
    serial_numbers: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    unit_cost: Decimal = Field(
        default=Decimal("0.00"), sa_column=Column(Numeric(12, 2), nullable=False)
    )
    created_at: datetime = Field(
        default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False)
    )

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Index, Numeric, String, UniqueConstraint
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
    # Contact & address details (used on quotes, invoices)
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
        UniqueConstraint("company_id", "normalized_phone", name="uq_leads_company_phone"),
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
    # e.g. "en", "hi", "ta", "te", "kn", "mr", "gu", "bn", "pa", "ml"
    company_name: Optional[str] = Field(default=None, max_length=200)
    designation: Optional[str] = Field(default=None, max_length=150)
    # B2B billing details for quotes
    billing_address: Optional[str] = Field(default=None, max_length=400)
    pincode: Optional[str] = Field(default=None, max_length=20)
    gst_number: Optional[str] = Field(default=None, max_length=50)
    deleted_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class Campaign(AuditMixin, table=True):
    __tablename__ = "campaigns"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
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
    is_active: bool = Field(default=True)


class Interaction(AuditMixin, table=True):
    __tablename__ = "interactions"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    lead_id: Optional[int] = Field(default=None, foreign_key="leads.id", index=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    campaign_id: Optional[int] = Field(default=None, foreign_key="campaigns.id", index=True)
    call_task_id: Optional[int] = Field(default=None, foreign_key="call_tasks.id", index=True)
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
    # Claim-lock: set to now() when the worker starts processing this recipient.
    # Workers skip rows where this is within the last 10 minutes (prevents double-send
    # when a worker crashes mid-step and restarts before the next cycle).
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
    # Canonical short form of the objection, e.g. "too expensive"
    objection_key: str = Field(max_length=200)
    # Human-readable label shown in the UI (same as key unless edited)
    objection_text: str = Field(max_length=500)
    # One of: price | competitor | timing | need | general
    category: str = Field(default="general", max_length=50)
    # Suggested rebuttal (editable by admins)
    rebuttal: Optional[str] = None
    # How many times this has been raised (auto-incremented on extraction)
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
    score_rapport: Optional[int] = None          # opening / tone
    score_discovery: Optional[int] = None        # questions asked, needs uncovered
    score_objection_handling: Optional[int] = None
    score_value_proposition: Optional[int] = None
    score_closing: Optional[int] = None          # clear CTA / next step set
    score_overall: Optional[int] = None          # weighted composite

    # LLM-generated summary and recommended prompt fix
    strengths: Optional[str] = None
    weaknesses: Optional[str] = None
    prompt_suggestion: Optional[str] = None      # the actual improved system-prompt snippet
    prompt_applied: bool = Field(default=False)  # True once auto-tune writes it


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
    # Normalised lowercase competitor name, e.g. "salesforce", "hubspot"
    competitor_name: str = Field(max_length=200, index=True)
    # Raw snippet from the transcript that triggered the detection
    mention_snippet: Optional[str] = Field(default=None, max_length=500)
    # Optional counter-script the AI should use when this competitor is mentioned
    counter_script: Optional[str] = None
    # Source: "realtime" (voice pipeline keyword match) or "post_call" (LLM extraction)
    source: str = Field(default="post_call", max_length=50)
    detected_at: Optional[datetime] = Field(default_factory=utc_now)


class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


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

    rating: Optional[int] = Field(default=None)           # 1–5
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

    status: str = Field(default="pending", max_length=20)  # pending | sent | failed
    attempts: int = Field(default=0)
    max_attempts: int = Field(default=5)
    next_attempt_at: datetime = Field(default_factory=utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    sent_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))
    last_issue: Optional[str] = None


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
    status: str = Field(default="pending", max_length=30)  # pending | running | done | failed
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
    description: Optional[str] = None
    target_audience_rule: Optional[str] = None


class CampaignStepCreate(SQLModel):
    step_order: int
    channel: str
    template_id: Optional[int] = None
    delay_hours: int = 0
    objective: Optional[str] = None


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


class CallTaskCreate(SQLModel):
    lead_id: int
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

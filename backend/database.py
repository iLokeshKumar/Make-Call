import logging
import os
from contextvars import ContextVar
from typing import Generator, Optional

from dotenv import load_dotenv
from sqlalchemy import event, text as sa_text
from sqlalchemy.orm import Session as _SASession
from sqlmodel import SQLModel, Session, create_engine, select

from models.models import Permission, Role, RolePermission

logger = logging.getLogger(__name__)

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(
    DATABASE_URL,
    echo=os.getenv("SQL_ECHO", "0") == "1",
    pool_pre_ping=True,
)

rls_company_id: ContextVar[Optional[int]] = ContextVar("rls_company_id", default=None)


_RLS_WARN_ENABLED = os.getenv("RLS_WARN_ON_MISSING", "1") == "1"


@event.listens_for(_SASession, "after_begin", propagate=True)
def _apply_rls_context(session: _SASession, transaction, connection) -> None:  # type: ignore[type-arg]
    """
    Fires once per transaction begin on every SQLAlchemy Session.
    Injects SET LOCAL so the Postgres RLS policy can read it.
    SET LOCAL is transaction-scoped — resets automatically on commit/rollback,
    so pooled connections are never left with a stale company_id.
    """
    cid = rls_company_id.get()
    if cid is not None:
        connection.execute(sa_text(f"SET LOCAL app.current_company_id = {int(cid)}"))
    elif _RLS_WARN_ENABLED:
        logger.warning(
            "DB session opened without rls_company_id — RLS policies will "
            "see all rows. This is expected for init/migrations but not for "
            "request or worker code.",
            stacklevel=2,
        )


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


def seed_permissions(session: Session) -> None:
    defaults = [
        ("lead.read_own", "lead", "Read own leads"),
        ("lead.read_company", "lead", "Read all company leads"),
        ("lead.create", "lead", "Create leads"),
        ("lead.update_own", "lead", "Update own leads"),
        ("lead.update_company", "lead", "Update all company leads"),
        ("lead.delete_own", "lead", "Delete own leads"),
        ("lead.delete_company", "lead", "Delete all company leads"),
        ("interaction.read_own", "interaction", "Read own interactions"),
        ("interaction.read_company", "interaction", "Read all company interactions"),
        ("product.read", "product", "Read products"),
        ("product.manage", "product", "Manage products"),
        ("appointment.read", "appointment", "Read appointments"),
        ("appointment.manage", "appointment", "Manage appointments"),
        ("outcome.read", "outcome", "Read outcomes"),
        ("outcome.manage", "outcome", "Manage outcomes"),
        ("user.invite", "user", "Invite users"),
        ("user.read", "user", "Read company users"),
        ("user.manage", "user", "Manage company users"),
        ("role.read", "role", "Read roles"),
        ("role.manage", "role", "Manage roles"),
        ("settings.read_company", "settings", "Read company settings"),
        ("settings.manage_company", "settings", "Manage company settings"),
        ("integrations.read_company", "integrations", "Read company integrations"),
        ("integrations.manage_company", "integrations", "Manage company integrations"),
        ("analytics.read_own", "analytics", "Read own analytics"),
        ("analytics.read_company", "analytics", "Read company analytics"),
        ("campaign.read", "campaign", "Read campaigns"),
        ("campaign.manage", "campaign", "Manage campaigns"),
        ("campaign.launch", "campaign", "Launch campaigns"),
        ("call_task.read", "call_task", "Read call tasks"),
        ("call_task.manage", "call_task", "Manage call tasks"),
        ("requirements.read", "requirements", "Read lead requirements"),
        ("requirements.manage", "requirements", "Manage lead requirements"),
        ("quote.read", "quote", "Read quotes"),
        ("quote.manage", "quote", "Manage quotes"),
        ("quote.send", "quote", "Send quotes"),
        ("agent.manage", "agent", "View and manage agent tasks"),
        ("agent.review", "agent", "Approve or reject agent actions"),
    ]

    existing = {item.key for item in session.exec(select(Permission)).all()}
    for key, module, description in defaults:
        if key not in existing:
            session.add(Permission(key=key, module=module, description=description))

    session.commit()


_SALES_REP_PERMISSIONS = {
    "lead.read_own", "lead.create", "lead.update_own",
    "interaction.read_own",
    "product.read",
    "appointment.read", "appointment.manage",
    "campaign.read",
    "call_task.read", "call_task.manage",
    "quote.read", "quote.manage", "quote.send",
    "analytics.read_own",
    "requirements.read", "requirements.manage",
    "user.read",
}


def patch_sales_rep_permissions(session: Session) -> None:
    """
    Idempotent — ensures every sales_representative role in every company
    has exactly the current set of sales permissions.
    Adds missing permissions and removes stale ones. Safe to run on every startup.
    """
    sales_roles = session.exec(
        select(Role).where(Role.name == "sales_representative")
    ).all()

    existing_keys = {p.key for p in session.exec(select(Permission)).all()}

    for role in sales_roles:
        existing_perms = set(session.exec(
            select(RolePermission.permission_key).where(RolePermission.role_id == role.id)
        ).all())

        # Add missing permissions
        for key in _SALES_REP_PERMISSIONS:
            if key in existing_keys and key not in existing_perms:
                session.add(RolePermission(role_id=role.id, permission_key=key))

        # Remove permissions no longer in the set
        stale = existing_perms - _SALES_REP_PERMISSIONS
        for key in stale:
            rp = session.exec(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_key == key,
                )
            ).first()
            if rp:
                session.delete(rp)

    session.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine, checkfirst=True)
    with Session(engine) as session:
        seed_permissions(session)
        patch_sales_rep_permissions(session)
    from migrations.apply_rls import ensure_rls
    ensure_rls()

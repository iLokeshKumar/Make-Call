import os
from typing import Generator

from dotenv import load_dotenv
from sqlmodel import SQLModel, Session, create_engine, select

from models.models import Permission

current_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(current_dir, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(
    DATABASE_URL,
    echo=True,
    pool_pre_ping=True,
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
    ]

    existing = {item.key for item in session.exec(select(Permission)).all()}
    for key, module, description in defaults:
        if key not in existing:
            session.add(Permission(key=key, module=module, description=description))

    session.commit()


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        seed_permissions(session)

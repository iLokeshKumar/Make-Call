import os
from typing import Optional

from sqlmodel import Session, select

from models.models import CompanySetting
from utils.encryption import decrypt_value


def get_company_setting_value(
    session: Session,
    company_id: int,
    key: str,
) -> Optional[str]:
    item = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if not item:
        return None
    return decrypt_value(item.value) if item.is_secret else item.value


def get_company_credential(
    session: Session,
    company_id: int,
    key: str,
    env_fallback: bool = True,
) -> Optional[str]:
    value = get_company_setting_value(session, company_id, key)
    if value:
        return value
    return os.getenv(key) if env_fallback else None


def get_credential(
    session: Session,
    company_id: int,
    key: str,
    default: Optional[str] = None,
    env_fallback: bool = True,
) -> Optional[str]:
    """Helper that mirrors the older get_credential signature."""
    value = get_company_setting_value(session, company_id, key)
    if value:
        return value
    if env_fallback:
        return os.getenv(key, default)
    return default

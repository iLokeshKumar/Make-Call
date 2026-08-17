import logging
from typing import Optional

from sqlmodel import Session, select

from models.models import ProviderCredential, utc_now

logger = logging.getLogger(__name__)


def _mask_value(value: str) -> str:
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]


def list_credentials(session: Session, company_id: int, provider: Optional[str] = None) -> list[ProviderCredential]:
    q = select(ProviderCredential).where(ProviderCredential.company_id == company_id)
    if provider:
        q = q.where(ProviderCredential.provider == provider)
    return session.exec(q.order_by(ProviderCredential.provider, ProviderCredential.key_name)).all()


def get_credential(session: Session, company_id: int, credential_id: int) -> Optional[ProviderCredential]:
    return session.exec(
        select(ProviderCredential).where(
            ProviderCredential.id == credential_id,
            ProviderCredential.company_id == company_id,
        )
    ).first()


def create_credential(session: Session, company_id: int, data) -> ProviderCredential:
    from utils.encryption import encrypt_value
    existing = session.exec(
        select(ProviderCredential).where(
            ProviderCredential.company_id == company_id,
            ProviderCredential.provider == data.provider,
            ProviderCredential.key_name == data.key_name,
        )
    ).first()
    if existing:
        existing.value_encrypted = encrypt_value(data.value)
        existing.is_active = data.is_active
        existing.updated_at = utc_now()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    cred = ProviderCredential(
        company_id=company_id,
        provider=data.provider,
        key_name=data.key_name,
        value_encrypted=encrypt_value(data.value),
        is_active=data.is_active,
    )
    session.add(cred)
    session.commit()
    session.refresh(cred)
    return cred


def update_credential(session: Session, company_id: int, credential_id: int, data) -> Optional[ProviderCredential]:
    from utils.encryption import encrypt_value
    cred = get_credential(session, company_id, credential_id)
    if not cred:
        return None
    if data.value is not None:
        cred.value_encrypted = encrypt_value(data.value)
    if data.is_active is not None:
        cred.is_active = data.is_active
    cred.updated_at = utc_now()
    session.add(cred)
    session.commit()
    session.refresh(cred)
    return cred


def delete_credential(session: Session, company_id: int, credential_id: int) -> bool:
    cred = get_credential(session, company_id, credential_id)
    if not cred:
        return False
    session.delete(cred)
    session.commit()
    return True


def to_masked_read(cred: ProviderCredential) -> dict:
    return {
        "id": cred.id,
        "provider": cred.provider,
        "key_name": cred.key_name,
        "value_masked": _mask_value(cred.value_encrypted),
        "is_active": cred.is_active,
        "updated_at": cred.updated_at.isoformat() if cred.updated_at else None,
    }

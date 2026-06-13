"""
Per-company feature flags.

Resolution order (highest priority first):
  1. CompanyFeatureFlag row  (explicit DB override)
  2. Tier default            (derived from Company.subscription_tier)
  3. Global default          (True = on, unless listed as off-by-default)

Usage
-----
    from services.feature_flag_service import is_feature_enabled, require_feature

    # Soft check:
    if is_feature_enabled(session, company_id, "whatsapp"):
        ...

    # Hard guard — raises HTTP 403 if disabled:
    require_feature(session, company_id, "campaigns")
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Company, CompanyFeatureFlag

logger = logging.getLogger(__name__)

# List features that are OFF for a tier. Everything else defaults to ON. "enterprise" has no restrictions.

_TIER_OFF: dict[str, set[str]] = {
    "starter": set(),
    "growth": set(),
    "professional": set(),
    "enterprise": set(),
}

# Global fallback for unknown tiers: treat like starter
_FALLBACK_TIER = "starter"


def _tier_default(tier: str, feature: str) -> bool:
    off_set = _TIER_OFF.get(tier.lower(), _TIER_OFF[_FALLBACK_TIER])
    return feature not in off_set


# Avoids a DB hit on every request. Keys: (company_id, feature). Invalidated automatically after _CACHE_TTL_SECONDS.

_CACHE_TTL_SECONDS = 60
_cache: dict[tuple[int, str], tuple[bool, float]] = {}
_cache_lock = threading.Lock()


def _cache_get(company_id: int, feature: str) -> Optional[bool]:
    key = (company_id, feature)
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.monotonic() - entry[1] < _CACHE_TTL_SECONDS:
            return entry[0]
    return None


def _cache_set(company_id: int, feature: str, value: bool) -> None:
    key = (company_id, feature)
    with _cache_lock:
        _cache[key] = (value, time.monotonic())


def invalidate_cache(company_id: int, feature: Optional[str] = None) -> None:
    """Call after updating a CompanyFeatureFlag row."""
    with _cache_lock:
        if feature:
            _cache.pop((company_id, feature), None)
        else:
            # Invalidate all features for this company
            for k in list(_cache.keys()):
                if k[0] == company_id:
                    del _cache[k]


# Core check

def is_feature_enabled(session: Session, company_id: int, feature: str) -> bool:
    """
    Return True if `feature` is enabled for `company_id`.
    Never raises — returns True on any unexpected error (fail-open).
    """
    cached = _cache_get(company_id, feature)
    if cached is not None:
        return cached

    try:
        # 1. Explicit DB override
        override = session.exec(
            select(CompanyFeatureFlag).where(
                CompanyFeatureFlag.company_id == company_id,
                CompanyFeatureFlag.feature == feature,
            )
        ).first()
        if override is not None:
            result = override.enabled
            _cache_set(company_id, feature, result)
            return result

        # 2. Tier default
        company = session.get(Company, company_id)
        tier = (company.subscription_tier if company else _FALLBACK_TIER)
        result = _tier_default(tier, feature)
        _cache_set(company_id, feature, result)
        return result

    except Exception as exc:
        logger.warning("feature_flag check failed company=%s feature=%s: %s", company_id, feature, exc)
        return True


def require_feature(session: Session, company_id: int, feature: str) -> None:
    """
    Raise HTTP 403 if `feature` is disabled for `company_id`.
    Use as a one-liner at the top of any route that needs a gate.
    """
    if not is_feature_enabled(session, company_id, feature):
        raise HTTPException(
            status_code=403,
            detail=f"The '{feature}' feature is not available on your current plan.",
        )


# Admin helpers

def set_feature_flag(
    session: Session,
    company_id: int,
    feature: str,
    enabled: bool,
    actor_note: str = "",
) -> CompanyFeatureFlag:
    """
    Upsert an explicit feature flag for a company.
    Call invalidate_cache() is handled automatically here.
    """
    from models.models import utc_now

    flag = session.exec(
        select(CompanyFeatureFlag).where(
            CompanyFeatureFlag.company_id == company_id,
            CompanyFeatureFlag.feature == feature,
        )
    ).first()

    if flag:
        flag.enabled    = enabled
        flag.updated_at = utc_now()
    else:
        flag = CompanyFeatureFlag(
            company_id=company_id,
            feature=feature,
            enabled=enabled,
        )
        session.add(flag)

    session.commit()
    session.refresh(flag)
    invalidate_cache(company_id, feature)
    logger.info(
        "feature_flag updated company=%s feature=%s enabled=%s note=%r",
        company_id, feature, enabled, actor_note,
    )
    return flag


def get_all_flags(session: Session, company_id: int) -> dict[str, bool]:
    """
    Return a full feature map for a company — tier defaults merged with
    explicit overrides.  Useful for the settings page / admin panel.
    """
    company  = session.get(Company, company_id)
    tier     = (company.subscription_tier if company else _FALLBACK_TIER)
    overrides = {
        row.feature: row.enabled
        for row in session.exec(
            select(CompanyFeatureFlag).where(
                CompanyFeatureFlag.company_id == company_id
            )
        ).all()
    }

    # Collect all known feature names
    all_features: set[str] = set()
    for off_set in _TIER_OFF.values():
        all_features |= off_set
    all_features |= set(overrides.keys())

    return {
        f: overrides[f] if f in overrides else _tier_default(tier, f)
        for f in sorted(all_features)
    }

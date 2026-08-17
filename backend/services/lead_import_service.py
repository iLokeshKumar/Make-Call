"""
Lead import service — handles CSV/Excel, Apollo, Lusha, LinkedIn, JustDial, IndiaMart.
Each importer returns a list of normalised lead dicts ready for bulk DB insertion.
"""
import io
import logging
import re
from typing import Any

import requests
from sqlmodel import Session, select

from credentials_service import get_company_credential
from models.models import Lead, User, utc_now

logger = logging.getLogger(__name__)


# Phone normalisation (basic — keeps digits + leading +)

def _norm_phone(raw: str | None) -> str:
    if not raw:
        return ""
    raw = str(raw).strip()
    digits = re.sub(r"[^\d+]", "", raw)
    if digits.startswith("+"):
        return digits[:16]
    if len(digits) == 10 and digits[0] in "6789":
        return f"+91{digits}"
    if len(digits) == 12 and digits.startswith("91"):
        return f"+{digits}"
    return digits[:16] if digits else ""


# Column mapper — resolves flexible header aliases to canonical field names

_COLUMN_ALIASES: dict[str, list[str]] = {
    "name":              ["name", "contact name", "contact person", "full name", "lead name",
                          "person name", "customer name", "owner"],
    "first_name":        ["first name", "firstname"],
    "last_name":         ["last name", "lastname", "surname"],
    "normalized_phone":  ["phone", "mobile", "contact mobile", "phone number", "contact number",
                          "whatsapp", "cell", "telephone", "mobile number", "direct phone",
                          "mobile phone", "hq phone"],
    "email":             ["email", "email address", "contact email", "e-mail", "mail",
                          "email_address"],
    "company_name":      ["company", "company name", "organization", "organisation", "firm",
                          "business name", "account name", "companyname"],
    "job_title":         ["title", "job title", "designation", "position", "role"],
    "industry":          ["industry", "category", "sector", "business type", "nature of business"],
    "city":              ["city", "town", "location"],
    "state":             ["state", "province", "region"],
    "country":           ["country"],
    "website":           ["website", "url", "web", "linkedin url", "company website"],
    "notes":             ["notes", "remarks", "comments", "description", "message", "query"],
    "source":            ["source", "lead source", "channel"],
}


def _build_col_map(headers: list[str]) -> dict[str, str]:
    """Return {csv_header: canonical_field} for headers we recognise."""
    mapping: dict[str, str] = {}
    lowered = [h.lower().strip() for h in headers]
    for canonical, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lowered:
                idx = lowered.index(alias)
                mapping[headers[idx]] = canonical
                break
    return mapping


def _row_to_lead_dict(row: dict[str, Any], col_map: dict[str, str], source_tag: str) -> dict | None:
    """Map a raw CSV row to a normalised lead dict. Returns None if unusable."""
    mapped: dict[str, Any] = {}
    for csv_col, canonical in col_map.items():
        val = str(row.get(csv_col, "") or "").strip()
        if val:
            mapped[canonical] = val

    # Merge first+last if no full name
    if "name" not in mapped:
        fn = mapped.pop("first_name", "")
        ln = mapped.pop("last_name", "")
        full = f"{fn} {ln}".strip()
        if full:
            mapped["name"] = full
    mapped.pop("first_name", None)
    mapped.pop("last_name", None)

    phone = _norm_phone(mapped.get("normalized_phone"))
    mapped["normalized_phone"] = phone

    if not mapped.get("name") or not phone:
        return None

    mapped.setdefault("source", source_tag)
    return mapped


# CSV / Excel parser

def parse_file_upload(file_bytes: bytes, filename: str, source_tag: str = "csv_import") -> list[dict]:
    """Parse CSV or XLSX bytes into a list of normalised lead dicts."""
    import pandas as pd

    fname = filename.lower()
    if fname.endswith((".xlsx", ".xls")):
        df = pd.read_excel(io.BytesIO(file_bytes), dtype=str)
    else:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str)
        except Exception:
            df = pd.read_csv(io.BytesIO(file_bytes), dtype=str, encoding="latin-1")

    df.columns = [str(c).strip() for c in df.columns]
    df = df.where(df.notna(), None)

    col_map = _build_col_map(list(df.columns))
    leads = []
    for _, row in df.iterrows():
        ld = _row_to_lead_dict(row.to_dict(), col_map, source_tag)
        if ld:
            leads.append(ld)
    return leads


# Apollo search importer

APOLLO_SEARCH_URL = "https://api.apollo.io/v1/mixed_people/search"


def search_apollo_leads(
    api_key: str,
    job_titles: list[str] | None = None,
    locations: list[str] | None = None,
    companies: list[str] | None = None,
    keywords: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """Search Apollo people API and return normalised lead dicts."""
    headers = {
        "X-Api-Key": api_key,
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }
    payload: dict[str, Any] = {
        "page": 1,
        "per_page": min(limit, 100),
        "prospected_by_current_team": ["no"],
    }
    if job_titles:
        payload["person_titles"] = job_titles
    if locations:
        payload["person_locations"] = locations
    if companies:
        payload["organization_names"] = companies
    if keywords:
        payload["q_keywords"] = keywords

    try:
        resp = requests.post(APOLLO_SEARCH_URL, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("[Apollo Import] API call failed: %s", exc)
        raise RuntimeError(f"Apollo API error: {exc}") from exc

    leads = []
    for person in data.get("people", []) or []:
        phone = (
            person.get("sanitized_phone")
            or (person.get("phone_numbers") or [{}])[0].get("sanitized_number", "")
        )
        phone = _norm_phone(phone)
        if not phone:
            continue

        org = person.get("organization") or {}
        name = f"{person.get('first_name','') or ''} {person.get('last_name','') or ''}".strip()
        if not name:
            continue

        leads.append({
            "name": name,
            "normalized_phone": phone,
            "email": person.get("email") or None,
            "job_title": person.get("title") or None,
            "company_name": org.get("name") or person.get("organization_name") or None,
            "industry": org.get("industry") or None,
            "city": person.get("city") or None,
            "state": person.get("state") or None,
            "country": person.get("country") or None,
            "website": org.get("website_url") or None,
            "source": "apollo",
        })
    return leads


# Lusha search importer

LUSHA_PERSON_URL = "https://api.lusha.com/person"


def search_lusha_leads(
    api_key: str,
    queries: list[dict],   # [{first_name, last_name, company}]
) -> list[dict]:
    """
    Lookup contacts via Lusha person API.
    queries = [{"first_name": "...", "last_name": "...", "company": "..."}]
    """
    headers = {"api_key": api_key}
    leads = []
    for q in queries[:50]:   # cap at 50 lookups per import
        params = {
            "firstName": q.get("first_name", ""),
            "lastName": q.get("last_name", ""),
            "company": q.get("company", ""),
        }
        try:
            resp = requests.get(LUSHA_PERSON_URL, headers=headers, params=params, timeout=10)
            if resp.status_code != 200:
                continue
            person = resp.json()
        except Exception:
            continue

        phones = person.get("phoneNumbers") or []
        phone = _norm_phone(phones[0].get("normalizedNumber", "") if phones else "")
        if not phone:
            continue

        emails = person.get("emailAddresses") or []
        email = emails[0].get("email") if emails else None
        name = f"{q.get('first_name','')} {q.get('last_name','')}".strip() or person.get("name", "")

        leads.append({
            "name": name,
            "normalized_phone": phone,
            "email": email or None,
            "job_title": person.get("jobTitle") or None,
            "company_name": q.get("company") or None,
            "city": person.get("city") or None,
            "country": person.get("country") or None,
            "source": "lusha",
        })
    return leads


# ZoomInfo API importer
# ZoomInfo uses a two-step auth: POST /authenticate → JWT, then POST /search/contact
# From Docs: https://api-docs.zoominfo.com/

ZOOMINFO_AUTH_URL = "https://api.zoominfo.com/authenticate"
ZOOMINFO_SEARCH_URL = "https://api.zoominfo.com/search/contact"


def _zoominfo_token(client_id: str, private_key: str) -> str:
    """
    Exchange ZoomInfo client_id + private_key for a short-lived JWT.
    ZoomInfo accepts either RSA-signed JWT or username/password depending on plan.
    We use the username/password (partner key) flow that most API plans support.
    """
    payload = {"username": client_id, "password": private_key}
    resp = requests.post(ZOOMINFO_AUTH_URL, json=payload, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"ZoomInfo auth failed ({resp.status_code}): {resp.text[:200]}")
    data = resp.json()
    token = data.get("jwt") or data.get("access_token") or data.get("token")
    if not token:
        raise RuntimeError("ZoomInfo auth response did not contain a token")
    return token


def search_zoominfo_leads(
    client_id: str,
    private_key: str,
    job_titles: list[str] | None = None,
    locations: list[str] | None = None,
    companies: list[str] | None = None,
    departments: list[str] | None = None,
    keywords: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """
    Search ZoomInfo contact database and return normalised lead dicts.

    Auth:  client_id = ZoomInfo username / client ID
           private_key = ZoomInfo password / API key
    """
    token = _zoominfo_token(client_id, private_key)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # Build filter clauses
    filters: list[dict] = []
    if job_titles:
        filters.append({"field": "jobTitle", "values": job_titles})
    if companies:
        filters.append({"field": "companyName", "values": companies})
    if departments:
        filters.append({"field": "department", "values": departments})
    if locations:
        # ZoomInfo uses city / state / country as separate fields; pass as metroArea
        filters.append({"field": "metroArea", "values": locations})

    search_body: dict[str, Any] = {
        "outputFields": [
            "id", "firstName", "lastName", "jobTitle", "phone", "email",
            "companyName", "city", "state", "country", "industry", "website",
        ],
        "rpp": min(limit, 100),
        "page": 1,
        "matchType": "PERSON",
    }
    if filters:
        search_body["filterValues"] = filters
    if keywords:
        search_body["keywords"] = keywords

    try:
        resp = requests.post(ZOOMINFO_SEARCH_URL, headers=headers, json=search_body, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.error("[ZoomInfo Import] Search failed: %s", exc)
        raise RuntimeError(f"ZoomInfo API error: {exc}") from exc

    leads = []
    for person in data.get("data", {}).get("result", []) or []:
        phone = _norm_phone(person.get("phone") or "")
        if not phone:
            continue
        name = f"{person.get('firstName','') or ''} {person.get('lastName','') or ''}".strip()
        if not name:
            continue
        leads.append({
            "name": name,
            "normalized_phone": phone,
            "email": person.get("email") or None,
            "job_title": person.get("jobTitle") or None,
            "company_name": person.get("companyName") or None,
            "industry": person.get("industry") or None,
            "city": person.get("city") or None,
            "state": person.get("state") or None,
            "country": person.get("country") or None,
            "website": person.get("website") or None,
            "source": "zoominfo",
        })
    return leads


# Bulk insert (shared by all importers)

def bulk_create_leads(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_dicts: list[dict],
) -> dict:
    """
    Insert leads from normalised dicts. Skips duplicates by phone.
    Returns {imported, skipped, errors}.
    """
    imported = 0
    skipped = 0
    errors: list[str] = []

    for ld in lead_dicts:
        phone = ld.get("normalized_phone", "").strip()
        if not phone:
            skipped += 1
            continue

        # Duplicate check
        existing = session.exec(
            select(Lead).where(
                Lead.company_id == company_id,
                Lead.normalized_phone == phone,
            )
        ).first()
        if existing:
            skipped += 1
            continue

        try:
            lead = Lead(
                company_id=company_id,
                owner_user_id=actor_user_id,
                name=(ld.get("name") or "Unknown").strip()[:200],
                normalized_phone=phone[:30],
                email=(ld.get("email") or "").strip().lower() or None,
                job_title=(ld.get("job_title") or "")[:150] or None,
                company_name=(ld.get("company_name") or "")[:200] or None,
                designation=(ld.get("job_title") or "")[:150] or None,
                industry=(ld.get("industry") or "")[:100] or None,
                website=(ld.get("website") or "")[:255] or None,
                city=(ld.get("city") or "")[:100] or None,
                state=(ld.get("state") or "")[:100] or None,
                country=(ld.get("country") or "")[:100] or None,
                notes=ld.get("notes") or None,
                source=ld.get("source", "import")[:100],
                status="new",
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
            session.add(lead)
            session.flush()
            imported += 1
        except Exception as exc:
            logger.warning("[BulkImport] Row skipped: %s — %s", ld.get("name"), exc)
            errors.append(f"{ld.get('name','?')}: {exc}")
            session.rollback()

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise RuntimeError(f"Bulk commit failed: {exc}") from exc

    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}

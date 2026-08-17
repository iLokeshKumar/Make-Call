from __future__ import annotations

import asyncio
import logging

import httpx

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)

_APOLLO_API_BASE = "https://api.apollo.io/api/v1"


def _get_apollo_token(session: Session, company_id: int) -> str:
    from routes.apollo_oauth import get_company_apollo_token
    token = get_company_apollo_token(session, company_id)
    if not token:
        raise ValueError("Apollo is not connected. Connect at Settings > Integrations > Apollo.io.")
    return token


def _apollo_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
    }


async def apollo_search_leads(
    company_id: int,
    job_title: str = "",
    industry: str = "",
    location: str = "",
    company_size: str = "",
    seniority: str = "",
    limit: int = 10,
) -> dict:
    def _load_token() -> str:
        tok = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return _get_apollo_token(session, company_id)
        finally:
            rls_company_id.reset(tok)

    async def _search(token: str) -> list[dict]:
        payload: dict = {"per_page": min(limit, 25), "page": 1}
        if job_title:
            payload["person_titles"] = [job_title]
        if industry:
            payload["organization_industry_tag_ids"] = [industry]
        if location:
            payload["person_locations"] = [location]
        if company_size:
            payload["organization_num_employees_ranges"] = [company_size]
        if seniority:
            payload["person_seniorities"] = [seniority]

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_APOLLO_API_BASE}/mixed_people/search",
                headers=_apollo_headers(token),
                json=payload,
            )
            resp.raise_for_status()
            people = resp.json().get("people", [])

        return [
            {
                "person_id": p.get("id"),
                "name": p.get("name"),
                "title": p.get("title"),
                "company": p.get("organization", {}).get("name"),
                "location": p.get("city") or p.get("country"),
                "linkedin_url": p.get("linkedin_url"),
                "email": p.get("email"),
                "phone": (p.get("phone_numbers") or [{}])[0].get("sanitized_number"),
            }
            for p in people
        ]

    try:
        token = await asyncio.to_thread(_load_token)
        results = await _search(token)
        return ToolResult.ok(results).model_dump()
    except Exception as exc:
        logger.error("[MCP:apollo_search_leads] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Apollo lead search failed: {exc}",
            next_suggestion="Check Apollo connection or try broader search filters.",
        ).model_dump()


async def apollo_enrich_contact(
    company_id: int,
    email: str = "",
    name: str = "",
    company_name: str = "",
) -> dict:
    if not email and not (name and company_name):
        return ToolResult.fail(
            "Provide email, or both name and company_name.",
            next_suggestion="Try: email='person@company.com' or name='John Doe' + company_name='Acme Corp'",
        ).model_dump()

    def _load_token() -> str:
        tok = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return _get_apollo_token(session, company_id)
        finally:
            rls_company_id.reset(tok)

    async def _enrich(token: str) -> dict:
        payload: dict = {"reveal_personal_emails": False}
        if email:
            payload["email"] = email
        if name:
            payload["name"] = name
        if company_name:
            payload["organization_name"] = company_name

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_APOLLO_API_BASE}/people/match",
                headers=_apollo_headers(token),
                json=payload,
            )
            resp.raise_for_status()
            person = resp.json().get("person") or {}

        return {
            "person_id": person.get("id"),
            "name": person.get("name"),
            "title": person.get("title"),
            "company": person.get("organization", {}).get("name"),
            "email": person.get("email"),
            "phone": (person.get("phone_numbers") or [{}])[0].get("sanitized_number"),
            "linkedin_url": person.get("linkedin_url"),
            "company_size": person.get("organization", {}).get("estimated_num_employees"),
            "industry": person.get("organization", {}).get("industry"),
            "location": person.get("city") or person.get("country"),
        }

    try:
        token = await asyncio.to_thread(_load_token)
        data = await _enrich(token)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:apollo_enrich_contact] company=%s email=%s error=%s", company_id, email, exc)
        return ToolResult.fail(
            f"Apollo enrichment failed: {exc}",
            next_suggestion="Verify Apollo is connected and the email/name is correct.",
        ).model_dump()

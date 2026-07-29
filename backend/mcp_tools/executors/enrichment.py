from __future__ import annotations

import asyncio
import logging
from typing import Optional

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session, select

logger = logging.getLogger(__name__)


def _run_sync(company_id: int, fn, *args, **kwargs):
    token = rls_company_id.set(company_id)
    try:
        with Session(engine) as session:
            return fn(session, company_id, *args, **kwargs)
    finally:
        rls_company_id.reset(token)


async def score_lead(company_id: int, lead_id: int) -> dict:
    from models.models import Lead
    from services.tabular.lead_scorer import score_lead_ml
    try:
        def _q(session, cid):
            lead = session.exec(
                select(Lead).where(Lead.id == lead_id, Lead.company_id == cid)
            ).first()
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            return score_lead_ml(session, cid, lead)

        result = await asyncio.to_thread(_run_sync, company_id, _q)

        raw_score = result.get("conversion_probability", 0.0)
        score_100 = round(raw_score * 100, 1)
        if score_100 >= 70:
            tier = "hot"
        elif score_100 >= 40:
            tier = "warm"
        else:
            tier = "cold"

        reasons = result.get("reasons", [])
        factors = [
            {"name": r, "impact": "positive" if "positive" in r or "enriched" in r or "senior" in r or "inbound" in r else "neutral", "weight": 1.0}
            for r in reasons
        ]
        return ToolResult.ok({
            "lead_id": lead_id,
            "score": score_100,
            "tier": tier,
            "factors": factors,
            "model": result.get("provider", "heuristic"),
        }).model_dump()
    except Exception as exc:
        logger.error("[enrichment] score_lead failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def recommend_channel(company_id: int, lead_id: int) -> dict:
    from models.models import Lead
    from services.tabular.channel_scorer import predict_best_channel
    try:
        def _q(session, cid):
            lead = session.exec(
                select(Lead).where(Lead.id == lead_id, Lead.company_id == cid)
            ).first()
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            return predict_best_channel(session, cid, lead)

        result = await asyncio.to_thread(_run_sync, company_id, _q)

        best = result.get("best_channel")
        confidences = result.get("confidences", {})
        confidence = confidences.get(best, 0.0) if best else 0.0
        provider = result.get("provider", "heuristic")
        reasoning = result.get("fallback_reason") or f"{provider} model prediction"

        return ToolResult.ok({
            "lead_id": lead_id,
            "recommended_channel": best,
            "confidence": round(confidence, 3),
            "channel_ranking": result.get("channel_ranking", []),
            "reasoning": reasoning,
            "model": provider,
        }).model_dump()
    except Exception as exc:
        logger.error("[enrichment] recommend_channel failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def check_opt_out(
    company_id: int,
    lead_id: int,
    channel: str,
) -> dict:
    from models.models import OptOut
    try:
        def _q(session, cid):
            record = session.exec(
                select(OptOut).where(
                    OptOut.company_id == cid,
                    OptOut.lead_id == lead_id,
                    OptOut.channel == channel,
                )
            ).first()
            return record

        record = await asyncio.to_thread(_run_sync, company_id, _q)
        opted_out = record is not None
        return ToolResult.ok({
            "lead_id": lead_id,
            "channel": channel,
            "opted_out": opted_out,
            "opted_out_at": record.created_at.isoformat() if record and record.created_at else None,
            "reason": record.reason if record else None,
        }).model_dump()
    except Exception as exc:
        logger.error("[enrichment] check_opt_out failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()

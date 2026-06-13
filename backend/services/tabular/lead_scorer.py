from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any

import numpy as np
from sqlmodel import Session, select

from models.models import Interaction, Lead, Quote, utc_now

logger = logging.getLogger(__name__)

MIN_ML_TRAIN_ROWS = 10

_model_cache: dict[int, object] = {}
_feature_cache: dict[int, dict[str, Any]] = {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _days_between(start, end) -> int:
    try:
        if not start or not end:
            return 0
        return max(0, int((end - start).days))
    except Exception:
        return 0


def _seniority_score(job_title: str | None) -> float:
    if not job_title:
        return 0.0
    title = job_title.lower()
    if any(kw in title for kw in ["ceo", "cfo", "cto", "cmo", "coo", "cxo", "owner", "founder", "vp", "president"]):
        return 1.0
    if any(kw in title for kw in ["director", "head", "senior manager", "sr manager"]):
        return 0.75
    if any(kw in title for kw in ["manager", "lead", "supervisor"]):
        return 0.5
    return 0.25


def _ism_stage_ordinal(stage: str | None) -> float:
    order = {"new": 0, "contacted": 1, "engaged": 2, "quote_sent": 3, "negotiation": 4, "closed_won": 5, "closed_lost": 6}
    return float(order.get((stage or "new").lower(), 0))


def _feature_row(lead: Lead, interactions: list[Interaction], quotes: list[Quote]) -> dict[str, Any]:
    call_count = sum(1 for i in interactions if i.channel == "call")
    email_count = sum(1 for i in interactions if i.channel == "email")
    whatsapp_count = sum(1 for i in interactions if i.channel == "whatsapp")
    inbound_count = sum(1 for i in interactions if i.direction == "inbound")
    reply_count = sum(1 for i in interactions if i.direction == "inbound" and i.channel != "call")
    sentiment_scores = []
    for i in interactions:
        meta = i.metadata_json or {}
        s = meta.get("sentiment")
        if s is not None:
            try:
                sentiment_scores.append(float(s))
            except (TypeError, ValueError):
                pass
    avg_sentiment = float(np.mean(sentiment_scores)) if sentiment_scores else 0.0
    total_amounts = [float(q.total_amount or 0) for q in quotes]
    max_deal_size = max(total_amounts) if total_amounts else 0.0
    days_since_created = _days_between(lead.created_at, utc_now())
    has_budget = 1 if lead.budget_range else 0
    has_timeline = 1 if lead.timeline else 0

    return {
        "lead_score": _safe_float(getattr(lead, "lead_score", None), 50.0),
        "industry": (lead.industry or "unknown").lower(),
        "source": (lead.source or "manual").lower(),
        "seniority": _seniority_score(lead.job_title),
        "ism_stage": _ism_stage_ordinal(lead.ism_stage),
        "days_since_created": float(days_since_created),
        "has_email": 1 if lead.email else 0,
        "has_website": 1 if lead.website else 0,
        "enrichment_score": 1.0 if (lead.enrichment_status or "") in ("basic_enriched", "fully_enriched") else 0.0,
        "call_count": float(call_count),
        "email_count": float(email_count),
        "whatsapp_count": float(whatsapp_count),
        "inbound_count": float(inbound_count),
        "reply_count": float(reply_count),
        "avg_sentiment": avg_sentiment,
        "max_deal_size": max_deal_size,
        "has_budget": float(has_budget),
        "has_timeline": float(has_timeline),
    }


def _normalized_features(row: dict[str, Any]) -> dict[str, float]:
    out = {}
    for k, v in row.items():
        if isinstance(v, str):
            out[k] = float(abs(hash(v)) % 1000)
        else:
            out[k] = float(v or 0.0)
    return out


def _baseline_score(features: dict[str, Any], reason: str) -> dict[str, Any]:
    base = features.get("lead_score", 50.0)
    seniority_bonus = float(features.get("seniority", 0)) * 15
    industry_penalty = 0.0
    industry = str(features.get("industry", "")).lower()
    if industry not in ("", "unknown") and industry not in {
        "tech", "saas", "manufacturing", "electronics",
        "healthcare", "finance", "retail", "distribution",
    }:
        industry_penalty = -10.0
    enrichment = 10.0 if float(features.get("enrichment_score", 0)) > 0 else 0.0
    budget_timeline = 5.0 if float(features.get("has_budget", 0)) > 0 else 0.0
    budget_timeline += 5.0 if float(features.get("has_timeline", 0)) > 0 else 0.0
    raw = base * 0.4 + seniority_bonus + industry_penalty + enrichment + budget_timeline
    raw = max(0.0, min(100.0, raw))
    priority = "high" if raw >= 70 else "medium" if raw >= 40 else "low"
    return {
        "provider": "heuristic_baseline",
        "fallback_reason": reason,
        "score": round(raw, 2),
        "priority": priority,
        "conversion_probability": round(raw / 100.0, 4),
        "reasons": [reason],
    }


def _load_training_data(session: Session, company_id: int) -> tuple[list[dict[str, Any]], list[str]]:
    closed_leads = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.ism_stage.in_(["closed_won", "closed_lost"]),
            Lead.deleted_at.is_(None),
        ).order_by(Lead.updated_at.desc()).limit(1000)
    ).all()

    rows: list[dict[str, Any]] = []
    labels: list[str] = []
    for lead in closed_leads:
        all_interactions = session.exec(
            select(Interaction).where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead.id,
            ).order_by(Interaction.created_at.desc())
        ).all()
        all_quotes = session.exec(
            select(Quote).where(
                Quote.company_id == company_id,
                Quote.lead_id == lead.id,
            ).order_by(Quote.created_at.desc())
        ).all()
        rows.append(_feature_row(lead, all_interactions, all_quotes))
        labels.append("won" if lead.ism_stage == "closed_won" else "not_won")
    return rows, labels


def _predict_with_tabpfn(
    train_rows: list[dict[str, Any]],
    labels: list[str],
    test_row: dict[str, Any],
) -> dict[str, Any]:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required") from exc
    try:
        from tabpfn import TabPFNClassifier
        import tabpfn
    except ImportError as exc:
        raise RuntimeError("tabpfn package is not installed") from exc

    normalized_train = [_normalized_features(r) for r in train_rows]
    normalized_test = _normalized_features(test_row)
    feature_names = list(normalized_test.keys())
    frame = pd.DataFrame(normalized_train + [normalized_test], columns=feature_names)
    frame = frame.fillna(0)
    x_train = frame.iloc[: len(train_rows)].to_numpy()
    x_test = frame.iloc[len(train_rows):].to_numpy()

    model_path = os.getenv("TABPFN_MODEL_PATH")
    thinking = os.getenv("TABPFN_THINKING_EFFORT")
    kwargs: dict[str, Any] = {}
    if model_path:
        kwargs["model_path"] = model_path
    if thinking:
        kwargs["thinking_effort"] = thinking

    clf = TabPFNClassifier(**kwargs)
    clf.fit(x_train, labels)
    proba = clf.predict_proba(x_test)
    classes = [str(c) for c in getattr(clf, "classes_", [])]
    first = list(proba[0])
    won_idx = classes.index("won") if "won" in classes else None
    win_prob = float(first[won_idx]) if won_idx is not None else float(max(first) if first else 0.5)

    model_version = getattr(tabpfn, "__version__", "unknown")
    return {
        "conversion_probability": win_prob,
        "score": round(win_prob * 100, 2),
        "priority": "high" if win_prob >= 0.7 else "medium" if win_prob >= 0.4 else "low",
        "classes": classes,
        "proba": [float(p) for p in first],
        "model_version": model_version,
    }


def score_lead_ml(
    session: Session,
    company_id: int,
    lead: Lead,
) -> dict[str, Any]:
    interactions = session.exec(
        select(Interaction).where(
            Interaction.company_id == company_id,
            Interaction.lead_id == lead.id,
        ).order_by(Interaction.created_at.desc())
    ).all()
    quotes = session.exec(
        select(Quote).where(
            Quote.company_id == company_id,
            Quote.lead_id == lead.id,
        ).order_by(Quote.created_at.desc())
    ).all()
    features = _feature_row(lead, interactions, quotes)

    train_rows, labels = _load_training_data(session, company_id)
    if len(train_rows) < MIN_ML_TRAIN_ROWS or len(set(labels)) < 2:
        return _baseline_score(features, "insufficient_training_data")

    try:
        result = _predict_with_tabpfn(train_rows, labels, features)
        reasons = [
            f"ml_prediction={result['conversion_probability']:.2%}",
            f"model=tabpfn-{result.get('model_version', 'unknown')}",
        ]
        if features["seniority"] >= 0.75:
            reasons.append("senior_decision_maker")
        if features["enrichment_score"] > 0:
            reasons.append("enriched_profile")
        if features["inbound_count"] > 0:
            reasons.append("inbound_engagement")
        if features["avg_sentiment"] > 0.5:
            reasons.append("positive_sentiment")
        result["reasons"] = reasons
        return result
    except Exception as exc:
        logger.warning("[LeadScorer] TabPFN failed, using baseline: %s", exc)
        return _baseline_score(features, f"tabpfn_fallback: {exc}")


def invalidate_lead_scorer_cache(company_id: int) -> None:
    _model_cache.pop(company_id, None)
    _feature_cache.pop(company_id, None)

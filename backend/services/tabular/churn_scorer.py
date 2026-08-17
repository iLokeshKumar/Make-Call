from __future__ import annotations

import logging
import os
from typing import Any

from sqlmodel import Session, select

from models.models import CallTask, Feedback, Interaction, Lead, utc_now

logger = logging.getLogger(__name__)

MIN_ML_TRAIN_ROWS = 15
SILENCE_THRESHOLD_DAYS = 14

_model_cache: dict[int, object] = {}


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


def _ism_stage_ordinal(stage: str | None) -> float:
    order = {"new": 0, "contacted": 1, "engaged": 2, "quote_sent": 3, "negotiation": 4, "closed_won": 5, "closed_lost": 6}
    return float(order.get((stage or "new").lower(), 0))


def _last_n_outcomes(session: Session, company_id: int, lead_id: int, n: int = 5) -> list[str]:
    tasks = session.exec(
        select(CallTask).where(
            CallTask.company_id == company_id,
            CallTask.lead_id == lead_id,
            CallTask.last_outcome.is_not(None),
        ).order_by(CallTask.created_at.desc()).limit(n)
    ).all()
    connected = {"completed", "in-progress", "connected"}
    return ["connected" if (t.last_outcome or "").lower() in connected else "missed" for t in tasks]


def _feature_row(
    session: Session,
    company_id: int,
    lead: Lead,
    interactions: list[Interaction],
) -> dict[str, Any]:
    outbound = [i for i in interactions if i.direction == "outbound"]
    inbound = [i for i in interactions if i.direction == "inbound"]
    call_count = sum(1 for i in outbound if i.channel == "call")
    email_count = sum(1 for i in outbound if i.channel == "email")
    whatsapp_count = sum(1 for i in outbound if i.channel == "whatsapp")
    reply_count = sum(1 for i in inbound)
    days_since_last_outreach = _days_between(lead.last_outreach_at, utc_now()) if lead.last_outreach_at else 999
    days_in_stage = _days_between(lead.updated_at, utc_now()) if lead.updated_at else 0
    last_5 = _last_n_outcomes(session, company_id, lead.id, 5)
    recent_connected = sum(1 for o in last_5 if o == "connected")

    feedback = session.exec(
        select(Feedback).where(
            Feedback.company_id == company_id,
            Feedback.lead_id == lead.id,
            Feedback.feedback_type == "csat",
            Feedback.rating.is_not(None),
        ).order_by(Feedback.created_at.desc()).limit(1)
    ).first()
    csat = feedback.rating if feedback else None

    return {
        "ism_stage": _ism_stage_ordinal(lead.ism_stage),
        "days_since_last_outreach": float(days_since_last_outreach),
        "days_in_stage": float(days_in_stage),
        "call_count": float(call_count),
        "email_count": float(email_count),
        "whatsapp_count": float(whatsapp_count),
        "total_outbound": float(len(outbound)),
        "total_inbound": float(len(inbound)),
        "reply_rate": float(len(inbound) / max(len(outbound), 1)),
        "recent_5_connected": float(recent_connected),
        "recent_5_total": float(len(last_5)),
        "csat_rating": float(csat) if csat else 0.0,
        "has_csat": 1.0 if csat else 0.0,
        "lead_score": _safe_float(getattr(lead, "lead_score", None), 50.0),
    }


def _normalized_features(row: dict[str, Any]) -> dict[str, float]:
    out = {}
    for k, v in row.items():
        if isinstance(v, str):
            out[k] = float(abs(hash(v)) % 1000)
        else:
            out[k] = float(v or 0.0)
    return out


def _baseline_risk(features: dict[str, Any], reason: str) -> dict[str, Any]:
    days_silent = features.get("days_since_last_outreach", 999)
    stage = features.get("ism_stage", 0)
    lead_score = features.get("lead_score", 50)
    reply_rate = features.get("reply_rate", 0)

    risk = 0.5
    reasons = [reason]
    if days_silent >= SILENCE_THRESHOLD_DAYS:
        risk = 0.9
        reasons.append(f"silent_{int(days_silent)}d")
    elif days_silent >= 7:
        risk = 0.7
        reasons.append(f"silent_{int(days_silent)}d")
    if stage >= 5:
        risk = 0.0
        reasons.append("terminal_stage")
    if reply_rate > 0.3:
        risk *= 0.6
        reasons.append("active_replier")
    if lead_score >= 70:
        risk *= 0.7
        reasons.append("high_lead_score")
    if lead_score < 30:
        risk = min(1.0, risk * 1.3)
        reasons.append("low_lead_score")
    risk = max(0.0, min(1.0, risk))

    return {
        "provider": "heuristic_baseline",
        "fallback_reason": reason,
        "disengagement_risk": round(risk, 4),
        "churn_risk_label": "high" if risk >= 0.7 else "medium" if risk >= 0.4 else "low",
        "reasons": reasons,
    }


def _load_training_data(session: Session, company_id: int) -> tuple[list[dict[str, Any]], list[str]]:
    now = utc_now()
    active_leads = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.deleted_at.is_(None),
            Lead.ism_stage.notin_(["closed_won", "closed_lost"]),
        ).limit(500)
    ).all()

    rows: list[dict[str, Any]] = []
    labels: list[str] = []
    for lead in active_leads:
        interactions = session.exec(
            select(Interaction).where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead.id,
            ).order_by(Interaction.created_at.desc())
        ).all()
        features = _feature_row(session, company_id, lead, interactions)
        rows.append(features)

        days_silent = _days_between(lead.last_outreach_at, now) if lead.last_outreach_at else 999
        reply_rate = features.get("reply_rate", 0)
        # Label: high-risk if silent > 14d with low reply rate, or terminal negative signals.
        if days_silent >= SILENCE_THRESHOLD_DAYS and reply_rate < 0.2:
            labels.append("churn_risk")
        elif days_silent >= 7 and reply_rate < 0.1:
            labels.append("churn_risk")
        else:
            labels.append("engaged")
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
    churn_idx = classes.index("churn_risk") if "churn_risk" in classes else None
    risk = float(first[churn_idx]) if churn_idx is not None else float(max(first) if first else 0.5)

    model_version = getattr(tabpfn, "__version__", "unknown")
    return {
        "provider": "tabpfn",
        "fallback_reason": None,
        "disengagement_risk": risk,
        "churn_risk_label": "high" if risk >= 0.7 else "medium" if risk >= 0.4 else "low",
        "classes": classes,
        "proba": [float(p) for p in first],
        "model_version": model_version,
    }


def predict_churn_risk(
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
    features = _feature_row(session, company_id, lead, interactions)

    train_rows, labels = _load_training_data(session, company_id)
    if len(train_rows) < MIN_ML_TRAIN_ROWS or len(set(labels)) < 2:
        return _baseline_risk(features, "insufficient_training_data")

    try:
        result = _predict_with_tabpfn(train_rows, labels, features)
        reasons = [
            f"risk={result['churn_risk_label']}",
            f"probability={result['disengagement_risk']:.1%}",
            f"model=tabpfn-{result.get('model_version', 'unknown')}",
        ]
        result["reasons"] = reasons
        return result
    except Exception as exc:
        logger.warning("[ChurnScorer] TabPFN failed, using baseline: %s", exc)
        return _baseline_risk(features, f"tabpfn_fallback: {exc}")


def invalidate_churn_scorer_cache(company_id: int) -> None:
    _model_cache.pop(company_id, None)

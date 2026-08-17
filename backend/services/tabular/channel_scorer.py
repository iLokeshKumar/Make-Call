from __future__ import annotations

import logging
import os
from typing import Any

from sqlmodel import Session, select

from models.models import Interaction, Lead, utc_now

logger = logging.getLogger(__name__)

MIN_ML_TRAIN_ROWS = 15

_model_cache: dict[int, object] = {}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _engagement_rate(interactions: list[Interaction], channel: str) -> float:
    outbound = [i for i in interactions if i.channel == channel and i.direction == "outbound"]
    if not outbound:
        return 0.0
    replies = sum(1 for i in interactions if i.channel == channel and i.direction == "inbound")
    return replies / len(outbound)


def _hour_of_day() -> float:
    return float(utc_now().hour)


def _day_of_week() -> float:
    return float(utc_now().weekday())


def _ism_stage_ordinal(stage: str | None) -> float:
    order = {"new": 0, "contacted": 1, "engaged": 2, "quote_sent": 3, "negotiation": 4, "closed_won": 5, "closed_lost": 6}
    return float(order.get((stage or "new").lower(), 0))


def _feature_row(
    lead: Lead,
    past_interactions: list[Interaction],
) -> dict[str, Any]:
    call_reply_rate = _engagement_rate(past_interactions, "call")
    email_reply_rate = _engagement_rate(past_interactions, "email")
    whatsapp_reply_rate = _engagement_rate(past_interactions, "whatsapp")
    total_outbound = len([i for i in past_interactions if i.direction == "outbound"])
    total_inbound = len([i for i in past_interactions if i.direction == "inbound"])

    return {
        "industry": (lead.industry or "unknown").lower(),
        "source": (lead.source or "manual").lower(),
        "ism_stage": _ism_stage_ordinal(lead.ism_stage),
        "hour_of_day": _hour_of_day(),
        "day_of_week": _day_of_week(),
        "has_phone": 1 if lead.normalized_phone else 0,
        "has_email": 1 if lead.email else 0,
        "total_outbound_attempts": float(total_outbound),
        "total_inbound_responses": float(total_inbound),
        "call_reply_rate": call_reply_rate,
        "email_reply_rate": email_reply_rate,
        "whatsapp_reply_rate": whatsapp_reply_rate,
    }


def _normalized_features(row: dict[str, Any]) -> dict[str, float]:
    out = {}
    for k, v in row.items():
        if isinstance(v, str):
            out[k] = float(abs(hash(v)) % 1000)
        else:
            out[k] = float(v or 0.0)
    return out


def _load_training_data(
    session: Session,
    company_id: int,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    leads = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.deleted_at.is_(None),
        ).limit(500)
    ).all()

    rows: list[dict[str, Any]] = []
    labels: list[str] = []
    channels: list[str] = []
    for lead in leads:
        interactions = session.exec(
            select(Interaction).where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead.id,
                Interaction.direction == "outbound",
            ).order_by(Interaction.created_at.desc())
        ).all()
        if not interactions:
            continue
        best_channel = _best_channel_from_history(interactions)
        if best_channel:
            all_interactions = session.exec(
                select(Interaction).where(
                    Interaction.company_id == company_id,
                    Interaction.lead_id == lead.id,
                ).order_by(Interaction.created_at.desc())
            ).all()
            rows.append(_feature_row(lead, all_interactions))
            labels.append(best_channel)
            channels.append(best_channel)
    return rows, labels, channels


def _best_channel_from_history(interactions: list[Interaction]) -> str | None:
    inbound = {i.channel for i in interactions if i.direction == "inbound" and i.channel}
    if inbound:
        channels = ["call", "whatsapp", "email"]
        for ch in channels:
            if ch in inbound:
                return ch
        return list(inbound)[0]
    last = max(interactions, key=lambda i: i.created_at or utc_now())
    return last.channel or "email"


def _infer_best_channel(lead: Lead, features: dict[str, Any], reason: str) -> dict[str, Any]:
    stage = (lead.ism_stage or "new").lower()
    stage_prefs = {
        "new": ["call", "whatsapp", "email"],
        "contacted": ["whatsapp", "call", "email"],
        "engaged": ["email", "whatsapp", "call"],
        "quote_sent": ["email", "whatsapp", "call"],
        "negotiation": ["call", "email", "whatsapp"],
    }
    ordered = stage_prefs.get(stage, ["call", "whatsapp", "email"])
    has_phone = bool(lead.normalized_phone)
    has_email = bool(lead.email)
    available = []
    for ch in ordered:
        if ch in ("call", "whatsapp") and not has_phone:
            continue
        if ch == "email" and not has_email:
            continue
        available.append(ch)
    if call_reply := features.get("call_reply_rate", 0):
        if call_reply > 0.3 and "call" in ordered and has_phone:
            available.insert(0, "call")
    if email_reply := features.get("email_reply_rate", 0):
        if email_reply > 0.3 and "email" in ordered:
            available.insert(0, "email")
    if whatsapp_reply := features.get("whatsapp_reply_rate", 0):
        if whatsapp_reply > 0.3 and "whatsapp" in ordered:
            available.insert(0, "whatsapp")

    seen = set()
    deduped = []
    for ch in available:
        if ch not in seen:
            seen.add(ch)
            deduped.append(ch)
    return {
        "provider": "heuristic",
        "fallback_reason": reason,
        "channel_ranking": deduped,
        "best_channel": deduped[0] if deduped else "call",
        "confidences": {ch: 1.0 / (i + 1) for i, ch in enumerate(deduped)},
    }


def _predict_with_tabpfn(
    train_rows: list[dict[str, Any]],
    labels: list[str],
    test_row: dict[str, Any],
    channels: list[str],
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
    all_classes = [str(c) for c in getattr(clf, "classes_", [])]
    probs = list(proba[0])
    channel_probs = {}
    for i, ch in enumerate(all_classes):
        channel_probs[ch] = float(probs[i]) if i < len(probs) else 0.0

    # Sort channels by probability, prefer ones the lead supports.
    has_phone = bool(test_row.get("has_phone", 1))
    has_email = bool(test_row.get("has_email", 1))
    scored = [(ch, prob) for ch, prob in channel_probs.items()]
    scored.sort(key=lambda x: -x[1])
    ranked = [ch for ch, _ in scored if (ch in ("call", "whatsapp") and has_phone) or (ch == "email" and has_email)]
    # Append any missing standard channels.
    for ch in ["call", "whatsapp", "email"]:
        if ch not in ranked and ((ch in ("call", "whatsapp") and has_phone) or (ch == "email" and has_email)):
            ranked.append(ch)

    model_version = getattr(tabpfn, "__version__", "unknown")
    return {
        "provider": "tabpfn",
        "fallback_reason": None,
        "channel_ranking": ranked,
        "best_channel": ranked[0] if ranked else "call",
        "confidences": channel_probs,
        "model_version": model_version,
    }


def predict_best_channel(
    session: Session,
    company_id: int,
    lead: Lead,
) -> dict[str, Any]:
    past_interactions = session.exec(
        select(Interaction).where(
            Interaction.company_id == company_id,
            Interaction.lead_id == lead.id,
        ).order_by(Interaction.created_at.desc())
    ).all()
    features = _feature_row(lead, past_interactions)
    has_phone = bool(lead.normalized_phone)
    has_email = bool(lead.email)

    if not has_phone and not has_email:
        return {
            "provider": "none",
            "best_channel": None,
            "channel_ranking": [],
            "confidences": {},
            "fallback_reason": "no_contact_channels",
        }

    train_rows, labels, channels = _load_training_data(session, company_id)
    if len(train_rows) < MIN_ML_TRAIN_ROWS or len(set(labels)) < 2:
        return _infer_best_channel(lead, features, "insufficient_training_data")

    try:
        result = _predict_with_tabpfn(train_rows, labels, features, channels)
        # Ensure only available channels.
        result["channel_ranking"] = [
            ch for ch in result["channel_ranking"]
            if (ch in ("call", "whatsapp") and has_phone) or (ch == "email" and has_email)
        ]
        if result["best_channel"] not in result["channel_ranking"]:
            result["channel_ranking"] = [ch for ch in ["call", "whatsapp", "email"] if (ch in ("call", "whatsapp") and has_phone) or (ch == "email" and has_email)]
            result["best_channel"] = result["channel_ranking"][0] if result["channel_ranking"] else None
        return result
    except Exception as exc:
        logger.warning("[ChannelScorer] TabPFN failed, using heuristic: %s", exc)
        return _infer_best_channel(lead, features, f"tabpfn_fallback: {exc}")


def invalidate_channel_scorer_cache(company_id: int) -> None:
    _model_cache.pop(company_id, None)

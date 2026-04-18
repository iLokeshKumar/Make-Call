"""
Predictive Dialer Service

Trains a lightweight model on historical call outcomes (connected vs not-connected)
grouped by hour-of-day and day-of-week, then scores upcoming time windows for a
specific lead so the campaign scheduler can pick the highest-probability slot.

Two modes:
  1. ML mode  — scikit-learn GradientBoostingClassifier (used when installed)
  2. Heuristic mode — pure Python fallback using outcome frequency tables

Features used:
  - hour_of_day   (0-23)
  - day_of_week   (0=Mon … 6=Sun)
  - lead_industry (one-hot, top 10 industries)
  - lead_source   (one-hot, top 5 sources)
  - ism_stage     (ordinal: new=0 … closed=6)

Target:
  - 1 = call connected (CallTask.last_outcome in {"completed", "in-progress"})
  - 0 = not connected  (no-answer, busy, failed, canceled)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from models.models import CallTask, Lead, utc_now

logger = logging.getLogger(__name__)

_CONNECTED = {"completed", "in-progress", "connected"}
_MISSED = {"no-answer", "busy", "failed", "canceled", "no_answer"}

_ISM_ORDINAL = {
    "new": 0, "contacted": 1, "engaged": 2, "quote_sent": 3,
    "negotiation": 4, "closed_won": 5, "closed_lost": 6,
}

_TOP_INDUSTRIES = [
    "technology", "manufacturing", "finance", "healthcare", "retail",
    "education", "real estate", "logistics", "hospitality", "telecom",
]
_TOP_SOURCES = ["manual", "apollo", "voice_agent", "webhook", "import"]


# Feature extraction

def _features_for_task(task: CallTask, lead: Optional[Lead]) -> list[float]:
    dt = task.started_at or task.created_at or utc_now()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    hour = dt.hour
    dow = dt.weekday()
    industry = (lead.industry or "").lower() if lead else ""
    source = (lead.source or "").lower() if lead else ""
    stage = _ISM_ORDINAL.get((lead.ism_stage or "new").lower(), 0) if lead else 0

    ind_vec = [1.0 if industry == i else 0.0 for i in _TOP_INDUSTRIES]
    src_vec = [1.0 if source == s else 0.0 for s in _TOP_SOURCES]

    return [float(hour), float(dow), float(stage)] + ind_vec + src_vec


def _features_for_slot(
    dt: datetime,
    lead: Optional[Lead],
) -> list[float]:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hour = dt.hour
    dow = dt.weekday()
    industry = (lead.industry or "").lower() if lead else ""
    source = (lead.source or "").lower() if lead else ""
    stage = _ISM_ORDINAL.get((lead.ism_stage or "new").lower(), 0) if lead else 0

    ind_vec = [1.0 if industry == i else 0.0 for i in _TOP_INDUSTRIES]
    src_vec = [1.0 if source == s else 0.0 for s in _TOP_SOURCES]

    return [float(hour), float(dow), float(stage)] + ind_vec + src_vec


# Heuristic fallback — pure Python frequency table

def _heuristic_score(
    company_tasks: list[CallTask],
    dt: datetime,
) -> float:
    """Return connection probability for this hour/dow using company's own frequency table."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    hour, dow = dt.hour, dt.weekday()

    connected = missed = 0
    for t in company_tasks:
        task_dt = t.started_at or t.created_at
        if not task_dt:
            continue
        if task_dt.tzinfo is None:
            task_dt = task_dt.replace(tzinfo=timezone.utc)
        if task_dt.hour == hour and task_dt.weekday() == dow:
            if (t.last_outcome or "").lower() in _CONNECTED:
                connected += 1
            elif (t.last_outcome or "").lower() in _MISSED:
                missed += 1

    total = connected + missed
    if total < 3:
        # Not enough data for this slot — use global rate with slight time-of-day prior
        global_conn = sum(1 for t in company_tasks if (t.last_outcome or "").lower() in _CONNECTED)
        global_total = sum(1 for t in company_tasks if (t.last_outcome or "").lower() in (_CONNECTED | _MISSED))
        base = global_conn / global_total if global_total > 0 else 0.35
        # Apply a simple time-of-day prior (business hours 9-12, 14-17 are better)
        if 9 <= hour <= 12 or 14 <= hour <= 17:
            return min(1.0, base * 1.2)
        if hour < 8 or hour > 20:
            return base * 0.5
        return base

    return connected / total


# ML model (optional, falls back gracefully)

_model_cache: dict[int, object] = {}  # company_id → fitted model


def _train_ml_model(X: list, y: list):
    try:
        from sklearn.ensemble import GradientBoostingClassifier
        import numpy as np
        clf = GradientBoostingClassifier(n_estimators=50, max_depth=3, random_state=42)
        clf.fit(np.array(X), np.array(y))
        return clf
    except ImportError:
        return None
    except Exception as exc:
        logger.warning("[PredictiveDialer] ML training failed: %s", exc)
        return None


def _ml_score(model, features: list) -> float:
    try:
        import numpy as np
        prob = model.predict_proba(np.array([features]))[0]
        # prob[1] = probability of class 1 (connected)
        return float(prob[1])
    except Exception:
        return 0.0


# Main API

def _load_training_data(session: Session, company_id: int):
    tasks = session.exec(
        select(CallTask).where(
            CallTask.company_id == company_id,
            CallTask.last_outcome.is_not(None),
        )
    ).all()
    return tasks


def get_best_call_windows(
    session: Session,
    company_id: int,
    lead_id: int,
    n_windows: int = 5,
    lookahead_hours: int = 72,
) -> list[dict]:
    """
    Return the top N call windows (within the next `lookahead_hours`) sorted by
    connection probability, from highest to lowest.
    """
    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)
    ).first()

    company_tasks = _load_training_data(session, company_id)
    labeled = [
        t for t in company_tasks
        if (t.last_outcome or "").lower() in (_CONNECTED | _MISSED)
    ]

    # Try ML model (train once per company, cache in memory)
    model = None
    if len(labeled) >= 20 and company_id not in _model_cache:
        leads_by_id: dict[int, Lead] = {}
        for t in labeled:
            if t.lead_id not in leads_by_id:
                l = session.get(Lead, t.lead_id)
                if l:
                    leads_by_id[t.lead_id] = l

        X = [_features_for_task(t, leads_by_id.get(t.lead_id)) for t in labeled]
        y = [1 if (t.last_outcome or "").lower() in _CONNECTED else 0 for t in labeled]
        _model_cache[company_id] = _train_ml_model(X, y)

    model = _model_cache.get(company_id)

    # Generate candidate slots (every hour for the next N hours)
    now = utc_now()
    slots: list[dict] = []
    for h in range(0, lookahead_hours):
        slot_dt = now + timedelta(hours=h)
        # Skip night hours (22:00–07:00 local-ish)
        if slot_dt.hour < 8 or slot_dt.hour > 20:
            continue

        features = _features_for_slot(slot_dt, lead)

        if model is not None:
            prob = _ml_score(model, features)
        else:
            prob = _heuristic_score(company_tasks, slot_dt)

        slots.append({
            "datetime": slot_dt.isoformat(),
            "hour": slot_dt.hour,
            "day_of_week": slot_dt.strftime("%A"),
            "probability": round(prob, 3),
            "confidence": "ml" if model else "heuristic",
        })

    # Sort by probability descending, return top N
    slots.sort(key=lambda s: s["probability"], reverse=True)
    top = slots[:n_windows]

    # Re-sort by datetime so UI can display them chronologically
    top.sort(key=lambda s: s["datetime"])

    return {
        "lead_id": lead_id,
        "model_type": "ml" if model else "heuristic",
        "training_samples": len(labeled),
        "windows": top,
    }


def invalidate_model_cache(company_id: int) -> None:
    """Call this when new call outcomes are recorded to force model retraining."""
    _model_cache.pop(company_id, None)

"""Excel-seeded training data for the TabPFN proposal scorer.

The TabPFN scorer (`proposal_predictor.score_proposal`) needs labelled
historical rows. A new company has none, so this service lets an admin upload
an Excel sheet of past deals (win/loss). Each parsed row is stored as a
`ProposalTrainingSample` and merged into the TabPFN training set.

Expected Excel columns (case-insensitive; unknown columns ignored):
  - one label column: `target` | `outcome` | `result` | `win`
    accepted values -> won:     won, win, yes, accepted, 1, true
                    -> not_won: lost, loss, no, rejected, expired, 0, false
  - any of the `_feature_row` feature names. Missing numeric features default
    to 0; missing categorical features default to "unknown".
"""
from __future__ import annotations

import io
import logging
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import ProposalTrainingSample

logger = logging.getLogger(__name__)

# Feature schema mirrors services.tabular.proposal_predictor._feature_row.
_CATEGORICAL_FEATURES = ("industry", "source", "intent_type")
_NUMERIC_FEATURES = (
    "lead_score",
    "intent_confidence",
    "matched_item_count",
    "unmatched_item_count",
    "missing_field_count",
    "stock_warning_count",
    "deal_size",
    "discount_percent",
    "validity_days",
    "has_budget",
    "has_timeline",
    "has_competitor",
    "knowledge_context_count",
)
_FEATURE_NAMES = _CATEGORICAL_FEATURES + _NUMERIC_FEATURES

_LABEL_COLUMNS = ("target", "outcome", "result", "win", "label")
_WON_VALUES = {"won", "win", "yes", "accepted", "1", "true", "y"}
_NOT_WON_VALUES = {"lost", "loss", "no", "rejected", "expired", "0", "false", "n", "not_won"}


def _norm_label(raw: Any) -> str | None:
    text = str(raw).strip().lower()
    if not text or text in {"nan", "none"}:
        return None
    if text in _WON_VALUES:
        return "won"
    if text in _NOT_WON_VALUES:
        return "not_won"
    return None


def _safe_float(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none"}:
            return 0.0
        return float(text)
    except Exception:
        return 0.0


def ingest_seed_excel(
    session: Session,
    company_id: int,
    actor_user_id: int,
    file_bytes: bytes,
) -> int:
    """Parse an uploaded Excel sheet and store labelled training rows.

    Returns the number of rows ingested. Raises HTTP 400 on a bad sheet.
    """
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - pandas ships with the backend
        raise HTTPException(status_code=500, detail="pandas is required for Excel seeding") from exc

    try:
        df = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {exc}") from exc

    if df.empty:
        raise HTTPException(status_code=400, detail="Excel sheet has no rows")

    # Case-insensitive column lookup.
    col_map = {str(c).strip().lower(): c for c in df.columns}
    label_col = next((col_map[name] for name in _LABEL_COLUMNS if name in col_map), None)
    if label_col is None:
        raise HTTPException(
            status_code=400,
            detail=f"Missing label column. Add one of: {', '.join(_LABEL_COLUMNS)}",
        )

    ingested = 0
    for _, row in df.iterrows():
        label = _norm_label(row.get(label_col))
        if label is None:
            continue
        features: dict[str, Any] = {}
        for name in _CATEGORICAL_FEATURES:
            src = col_map.get(name)
            value = row.get(src) if src is not None else None
            text = str(value).strip() if value is not None else ""
            features[name] = text or "unknown"
        for name in _NUMERIC_FEATURES:
            src = col_map.get(name)
            features[name] = _safe_float(row.get(src)) if src is not None else 0.0
        session.add(
            ProposalTrainingSample(
                company_id=company_id,
                label=label,
                features_json=features,
                source="excel_seed",
                created_by=actor_user_id,
                updated_by=actor_user_id,
            )
        )
        ingested += 1

    if ingested == 0:
        raise HTTPException(
            status_code=400,
            detail="No rows with a recognisable win/loss label were found",
        )

    session.commit()
    logger.info("[tabpfn-seed] company=%s ingested %s training rows", company_id, ingested)
    return ingested


def seed_rows(session: Session, company_id: int) -> tuple[list[dict[str, Any]], list[str]]:
    """Return stored seed samples as (feature_rows, labels) for TabPFN training."""
    samples = session.exec(
        select(ProposalTrainingSample).where(ProposalTrainingSample.company_id == company_id)
    ).all()
    rows: list[dict[str, Any]] = []
    labels: list[str] = []
    for sample in samples:
        features = dict(sample.features_json or {})
        if not features:
            continue
        # Ensure every expected feature is present (older seeds may lag schema).
        for name in _CATEGORICAL_FEATURES:
            features.setdefault(name, "unknown")
        for name in _NUMERIC_FEATURES:
            features.setdefault(name, 0.0)
        rows.append({k: features[k] for k in _FEATURE_NAMES})
        labels.append(sample.label)
    return rows, labels

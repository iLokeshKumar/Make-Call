from __future__ import annotations

import csv
import logging
import os
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from models.models import Lead, ProposalRequest, Quote

logger = logging.getLogger(__name__)

PRIORLABS_BASE_URL = os.getenv("PRIORLABS_API_BASE_URL", "https://api.priorlabs.ai").rstrip("/")
MIN_TABPFN_TRAIN_ROWS = 8


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


def _feature_row(lead: Lead | None, quote: Quote | None, spec: dict[str, Any], solution: dict[str, Any]) -> dict[str, Any]:
    matched_count = sum(1 for r in solution.get("recommended_items") or [] if r.get("matched"))
    unmatched_count = sum(1 for r in solution.get("recommended_items") or [] if not r.get("matched"))
    missing_count = len(spec.get("missing_fields") or [])
    total_amount = _safe_float(getattr(quote, "total_amount", None))
    discount_amount = _safe_float(getattr(quote, "discount_amount", None))
    discount_percent = (discount_amount / total_amount * 100.0) if total_amount > 0 else 0.0
    stock_warnings = sum(
        1
        for r in solution.get("recommended_items") or []
        if r.get("matched") and int((r["matched"].get("stock") or 0)) < int((r["matched"].get("quantity") or 1))
    )
    return {
        "lead_score": _safe_float(getattr(lead, "lead_score", None), 50.0),
        "industry": getattr(lead, "industry", None) or "unknown",
        "source": getattr(lead, "source", None) or "unknown",
        "intent_type": spec.get("intent") or "quote",
        "intent_confidence": _safe_float(spec.get("intent_confidence"), 0.0),
        "matched_item_count": matched_count,
        "unmatched_item_count": unmatched_count,
        "missing_field_count": missing_count,
        "stock_warning_count": stock_warnings,
        "deal_size": total_amount,
        "discount_percent": discount_percent,
        "validity_days": _days_between(getattr(quote, "created_at", None), getattr(quote, "valid_until", None)),
        "has_budget": 1 if spec.get("budget_range") else 0,
        "has_timeline": 1 if spec.get("timeline") else 0,
        "has_competitor": 1 if spec.get("competitors") else 0,
        "knowledge_context_count": len(solution.get("knowledge_context") or []),
    }


def _baseline_scores(features: dict[str, Any], reason: str) -> dict[str, Any]:
    missing = int(features.get("missing_field_count") or 0)
    unmatched = int(features.get("unmatched_item_count") or 0)
    matched = int(features.get("matched_item_count") or 0)
    stock = int(features.get("stock_warning_count") or 0)
    discount = Decimal(str(features.get("discount_percent") or 0))
    win = Decimal("0.50")
    win += Decimal("0.06") * matched
    win -= Decimal("0.10") * missing
    win -= Decimal("0.12") * unmatched
    win -= Decimal("0.05") * stock
    if discount > Decimal("15"):
        win -= Decimal("0.04")
    win = max(Decimal("0.05"), min(Decimal("0.92"), win))
    pricing_risk = "high" if stock or discount > Decimal("20") else ("medium" if missing or unmatched else "low")
    return {
        "provider": "local_tabular_baseline",
        "fallback_reason": reason,
        "win_probability": float(win),
        "missing_requirement_risk": float(min(Decimal("0.95"), Decimal("0.18") * missing)),
        "pricing_risk": pricing_risk,
        "recommended_discount_percent": 0.0 if missing or unmatched else 2.5,
        "features": features,
    }


def _historical_rows(session: Session, company_id: int) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    labels: list[str] = []
    proposals = session.exec(
        select(ProposalRequest)
        .where(ProposalRequest.company_id == company_id, ProposalRequest.quote_id.is_not(None))
        .order_by(ProposalRequest.created_at.desc())
        .limit(500)
    ).all()
    for proposal in proposals:
        quote = session.get(Quote, proposal.quote_id) if proposal.quote_id else None
        lead = session.get(Lead, proposal.lead_id)
        if not quote or not lead:
            continue
        status = (quote.status or "").lower()
        if status not in {"accepted", "rejected", "expired", "sent", "negotiation"}:
            continue
        rows.append(_feature_row(lead, quote, proposal.spec_json or {}, proposal.solution_json or {}))
        labels.append("won" if status == "accepted" else "not_won")

    # Merge admin-uploaded Excel seed rows so TabPFN has data before the
    # company accumulates real proposal/quote outcomes.
    try:
        from services.tabular.tabpfn_seed_service import seed_rows as _seed_rows
        seed_r, seed_l = _seed_rows(session, company_id)
        rows.extend(seed_r)
        labels.extend(seed_l)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[TabPFN] seed rows unavailable: %s", exc)
    return rows, labels


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _upload_file(httpx, url_info: dict[str, Any], path: Path) -> None:
    httpx.put(
        url_info["signed_urls"][0],
        content=path.read_bytes(),
        headers=url_info["required_headers"],
        timeout=120,
    ).raise_for_status()


def _predict_with_priorlabs_api(train_rows: list[dict[str, Any]], labels: list[str], test_row: dict[str, Any]) -> dict[str, Any]:
    token = os.getenv("PRIORLABS_API_KEY") or os.getenv("TABPFN_API_KEY")
    if not token:
        raise RuntimeError("PRIORLABS_API_KEY/TABPFN_API_KEY not configured")
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError("httpx is required for Prior Labs TabPFN API integration") from exc

    headers = {"Authorization": f"Bearer {token}"}
    fieldnames = list(test_row.keys())
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        x_train = root / "x_train.csv"
        y_train = root / "y_train.csv"
        x_test = root / "x_test.csv"
        _write_csv(x_train, train_rows, fieldnames)
        with y_train.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["target"])
            for label in labels:
                writer.writerow([label])
        _write_csv(x_test, [test_row], fieldnames)

        prep = httpx.post(
            f"{PRIORLABS_BASE_URL}/tabpfn/prepare_train_set_upload",
            headers=headers,
            json={"x_train_info": {"format": "csv"}, "y_train_info": {"format": "csv"}},
            timeout=30,
        )
        prep.raise_for_status()
        train_prep = prep.json()
        _upload_file(httpx, train_prep["x_train_info"], x_train)
        _upload_file(httpx, train_prep["y_train_info"], y_train)

        fit_payload: dict[str, Any] = {
            "train_set_upload_id": train_prep["train_set_upload_id"],
            "task": "classification",
        }
        if os.getenv("TABPFN_THINKING_MODE", "0") == "1":
            fit_payload.update({
                "thinking_effort": os.getenv("TABPFN_THINKING_EFFORT", "high"),
                "thinking_timeout_s": int(os.getenv("TABPFN_THINKING_TIMEOUT_S", "300")),
                "thinking_effort_metric": os.getenv("TABPFN_THINKING_METRIC", "log_loss"),
            })
        fit = httpx.post(f"{PRIORLABS_BASE_URL}/tabpfn/fit", headers=headers, json=fit_payload, timeout=420)
        fit.raise_for_status()
        fitted_train_set_id = fit.json()["fitted_train_set_id"]

        test_prep_res = httpx.post(
            f"{PRIORLABS_BASE_URL}/tabpfn/prepare_test_set_upload",
            headers=headers,
            json={"fitted_train_set_id": fitted_train_set_id, "x_test_info": {"format": "csv"}},
            timeout=30,
        )
        test_prep_res.raise_for_status()
        test_prep = test_prep_res.json()
        _upload_file(httpx, test_prep["x_test_info"], x_test)

        pred = httpx.post(
            f"{PRIORLABS_BASE_URL}/tabpfn/predict",
            headers=headers,
            json={
                "test_set_upload_id": test_prep["test_set_upload_id"],
                "fitted_train_set_id": fitted_train_set_id,
                "task_config": {
                    "task": "classification",
                    "predict_params": {"output_type": "probas"},
                },
            },
            timeout=120,
        )
        pred.raise_for_status()
        return pred.json()


def _predict_with_local_tabpfn(
    train_rows: list[dict[str, Any]],
    labels: list[str],
    test_row: dict[str, Any],
) -> dict[str, Any]:
    """Predict win probability with the locally installed `tabpfn` package.

    Runs fully on-prem (no Prior Labs API key needed). The first call downloads
    the pretrained TabPFN-3 weights from HuggingFace; set TABPFN_MODEL_PATH to use
    a pre-downloaded checkpoint and skip the network entirely.

    TabPFN-3 (tabpfn>=8.0) is the default. Supports thinking effort for improved
    accuracy at the cost of longer fit time.
    """
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is required for local TabPFN") from exc
    try:
        from tabpfn import TabPFNClassifier
        import tabpfn
    except ImportError as exc:
        raise RuntimeError("tabpfn package is not installed") from exc

    feature_names = list(test_row.keys())
    frame = pd.DataFrame(train_rows + [test_row], columns=feature_names)
    for col in frame.columns:
        if frame[col].dtype == object:
            frame[col] = frame[col].astype("category").cat.codes
    frame = frame.fillna(0)
    x_train = frame.iloc[: len(train_rows)].to_numpy()
    x_test = frame.iloc[len(train_rows):].to_numpy()

    model_path = os.getenv("TABPFN_MODEL_PATH")
    thinking_effort = os.getenv("TABPFN_THINKING_EFFORT")
    kwargs: dict[str, Any] = {}
    if model_path:
        kwargs["model_path"] = model_path
    if thinking_effort:
        kwargs["thinking_effort"] = thinking_effort

    clf = TabPFNClassifier(**kwargs)
    clf.fit(x_train, labels)
    proba = clf.predict_proba(x_test)
    classes = [str(c) for c in getattr(clf, "classes_", [])]
    first = list(proba[0])
    win_idx = classes.index("won") if "won" in classes else None
    win = float(first[win_idx]) if win_idx is not None else float(max(first) if first else 0.5)

    model_version = getattr(tabpfn, "__version__", "unknown")
    return {
        "win_probability": win,
        "classes": classes,
        "proba": [float(p) for p in first],
        "model_version": model_version,
    }


def score_proposal(
    session: Session,
    company_id: int,
    *,
    lead: Lead | None,
    quote: Quote | None,
    spec: dict[str, Any],
    solution: dict[str, Any],
) -> dict[str, Any]:
    """Score proposal quality with TabPFN, falling back gracefully.

    Provider order: local `tabpfn` package -> Prior Labs hosted API ->
    deterministic baseline. TabPFN needs labelled history; prior proposal/quote
    outcomes plus admin Excel-seeded rows are the training set, the current
    proposal is the single test row. Any failure falls through to the next
    provider so proposal creation is never blocked.
    """
    features = _feature_row(lead, quote, spec, solution)
    train_rows, labels = _historical_rows(session, company_id)
    if len(train_rows) < MIN_TABPFN_TRAIN_ROWS or len(set(labels)) < 2:
        return _baseline_scores(features, "insufficient_labelled_history_for_tabpfn")

    baseline = _baseline_scores(features, None)

    # 1) Local TabPFN package (preferred — on-prem, no API key).
    try:
        local = _predict_with_local_tabpfn(train_rows, labels, features)
        return {
            **baseline,
            "provider": "local_tabpfn",
            "fallback_reason": None,
            "win_probability": local["win_probability"],
            "raw_prediction": local["proba"],
            "metadata": {
                "engine": "tabpfn-local",
                "model_version": local.get("model_version"),
                "classes": local["classes"],
            },
        }
    except Exception as exc:  # noqa: BLE001
        logger.info("[TabPFN] local package unavailable, trying Prior Labs API: %s", exc)

    # 2) Prior Labs hosted TabPFN API.
    try:
        api_result = _predict_with_priorlabs_api(train_rows, labels, features)
        prediction = api_result.get("prediction")
        win_probability = None
        if isinstance(prediction, list) and prediction:
            first = prediction[0]
            if isinstance(first, dict):
                win_probability = first.get("won") or first.get("1")
            elif isinstance(first, list):
                # Prior Labs may return class-ordered probabilities depending on API version.
                win_probability = max(first) if first else None
        return {
            **baseline,
            "provider": "priorlabs_tabpfn",
            "fallback_reason": None,
            "win_probability": _safe_float(win_probability, 0.5),
            "raw_prediction": prediction,
            "metadata": api_result.get("metadata"),
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[TabPFN] Falling back to local proposal baseline: %s", exc)
        return _baseline_scores(features, f"tabpfn_unavailable: {exc}")


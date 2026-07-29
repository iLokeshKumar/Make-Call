"""
F3 Books-Sync Agent — Zoho Books → Tally Prime bridge.

Actions
-------
daily_sync    Pull new transactions from Zoho Books since the last watermark,
              stage as TallyStagingVoucher rows, log one ActionLedger batch
              proposal per run for audit trail.

push_voucher  Post one approved TallyStagingVoucher to the Tally Gateway
              (called by worker after accountant approves the staging batch).

retry_failed  Re-attempt all staging vouchers in status="failed" that still
              have retry_count < MAX_RETRIES.

reconcile     Compare Zoho Books closing balance vs Tally posted total for a
              date range; emit a drift KPI alert if gap > threshold.

Approval flow
-------------
  1. Worker runs daily_sync  → staged rows + ActionLedger proposal (A2)
  2. Accountant bulk-approves staging vouchers in /books-sync console
  3. Console sets vouchers to status="approved", queues push_voucher tasks
  4. Worker runs push_voucher → Tally Gateway → posted / failed
  5. Retry worker handles failed rows up to MAX_RETRIES

Zoho Books REST API
-------------------
Base: https://www.zohoapis.com/books/v3/
Auth: same OAuth token stored under provider="zoho" (Books + CRM share the
      same Zoho OAuth app; Books scope ZohoBooks.fullaccess.all must be added
      to the OAuth consent screen on first connect).

Tally Gateway
-------------
A lightweight FastAPI service that accepts Tally-XML payloads and POSTs them
to Tally Prime via the TCP XML interface (port 9000).
URL: env var TALLY_GATEWAY_URL (e.g. http://localhost:7200 or https://tally.internal)
If not set, push_voucher returns status="gateway_not_configured" — agent is safe
to deploy before the gateway is built.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import httpx
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select, func

from models.models import (
    AgentKpiEvent,
    AgentTask,
    TallyStagingVoucher,
    utc_now,
)
from services.action_ledger import (
    complete_action,
    fail_action,
    log_action,
    record_kpi,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_BOOKS_BASE = "https://www.zohoapis.com/books/v3"
_TALLY_GW_URL = os.getenv("TALLY_GATEWAY_URL", "")
_MAX_RETRIES = 3
_DRIFT_ALERT_INR = Decimal("5000")   # alert if Zoho vs Tally gap exceeds ₹5,000
_DEFAULT_SYNC_HOURS = 26             # pull last 26h on first run (covers overnight gap)
_ZOHO_ORG_ENV = "ZOHO_BOOKS_ORG_ID" # Zoho Books organization ID

# Voucher type → Tally voucher type name
_TALLY_TYPE_MAP: dict[str, str] = {
    "sales_invoice":     "Sales",
    "purchase_invoice":  "Purchase",
    "payment":           "Payment",
    "receipt":           "Receipt",
    "credit_note":       "Credit Note",
    "debit_note":        "Debit Note",
    "journal":           "Journal",
    "contra":            "Contra",
}


# ---------------------------------------------------------------------------
# Zoho Books helpers
# ---------------------------------------------------------------------------

def _get_books_token(session: Session, company_id: int) -> str:
    """Return the Zoho OAuth access token stored for this company.

    Books and CRM share the same Zoho OAuth app.
    We look for provider="zoho_books" first (future dedicated Books connection),
    then fall back to provider="zoho" (CRM token which also works for Books
    if the Books scope was included in the OAuth consent).
    """
    from sqlmodel import select as _select
    from models.models import ProviderCredential
    from utils.encryption import decrypt_value

    for provider in ("zoho_books", "zoho"):
        cred = session.exec(
            _select(ProviderCredential).where(
                ProviderCredential.company_id == company_id,
                ProviderCredential.provider == provider,
                ProviderCredential.key_name == "access_token",
                ProviderCredential.is_active == True,
            )
        ).first()
        if cred:
            try:
                token = decrypt_value(cred.value_encrypted)
                if token:
                    return token
            except Exception:
                pass

    raise ValueError(
        "Zoho Books not connected. Add ZohoBooks.fullaccess.all scope and reconnect "
        "at Settings > Integrations > Zoho."
    )


def _get_org_id(company_id: int) -> str:
    """Zoho Books requires an organization_id on every request."""
    org_id = os.getenv(_ZOHO_ORG_ENV, "")
    if not org_id:
        raise ValueError(
            f"Env var {_ZOHO_ORG_ENV} is not set. "
            "Find your Zoho Books Org ID at Settings > Organization Profile."
        )
    return org_id


def _books_headers(token: str) -> dict:
    return {"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"}


async def _fetch_books_page(
    url: str,
    params: dict,
    token: str,
    *,
    timeout: int = 30,
) -> list[dict]:
    """Fetch one page of Zoho Books results, handling pagination automatically."""
    all_items: list[dict] = []
    params = {**params, "page": 1, "per_page": 200}
    headers = _books_headers(token)

    async with httpx.AsyncClient(timeout=timeout) as client:
        while True:
            resp = await client.get(url, headers=headers, params=params)
            if resp.status_code == 401:
                raise ValueError("Zoho Books 401 — token expired. Re-authenticate at Settings > Integrations.")
            resp.raise_for_status()
            data = resp.json()

            # Zoho Books wraps results in keys like "invoices", "customerpayments" etc.
            # Find the first non-metadata list key.
            payload: list[dict] = []
            for k, v in data.items():
                if isinstance(v, list):
                    payload = v
                    break

            all_items.extend(payload)

            page_ctx = data.get("page_context", {})
            if not page_ctx.get("has_more_page", False):
                break
            params["page"] += 1

    return all_items


# ---------------------------------------------------------------------------
# Watermark — tracks last successful Zoho Books pull
# ---------------------------------------------------------------------------

def _get_watermark(session: Session, company_id: int) -> datetime:
    """Return the UTC timestamp of the last successful sync, or a default lookback."""
    latest = session.exec(
        select(AgentKpiEvent)
        .where(
            AgentKpiEvent.company_id == company_id,
            AgentKpiEvent.agent_name == "f3_books_sync",
            AgentKpiEvent.metric_name == "zoho_books_sync_watermark",
        )
        .order_by(AgentKpiEvent.created_at.desc())
    ).first()

    if latest and latest.metric_value:
        try:
            ts = float(latest.metric_value)
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, OSError):
            pass

    return datetime.now(timezone.utc) - timedelta(hours=_DEFAULT_SYNC_HOURS)


def _save_watermark(session: Session, company_id: int, ts: datetime) -> None:
    record_kpi(
        session,
        company_id,
        "f3_books_sync",
        "zoho_books_sync_watermark",
        str(ts.timestamp()),
    )


# ---------------------------------------------------------------------------
# Voucher mapping — Zoho Books JSON → Tally XML payload dict
# ---------------------------------------------------------------------------

def _map_to_tally_payload(voucher_type: str, zoho_row: dict) -> dict:
    """Convert a Zoho Books transaction row into the Tally Gateway request body.

    Returns a dict that the Tally Gateway serializes into Tally Prime XML.
    The gateway owns the final XML serialization; we produce the logical payload.
    """
    tally_type = _TALLY_TYPE_MAP.get(voucher_type, "Journal")

    # Zoho Books field names vary by transaction type
    party = (
        zoho_row.get("customer_name")
        or zoho_row.get("vendor_name")
        or zoho_row.get("contact_name")
        or ""
    )
    ref_number = (
        zoho_row.get("invoice_number")
        or zoho_row.get("bill_number")
        or zoho_row.get("payment_number")
        or zoho_row.get("creditnote_number")
        or zoho_row.get("journal_number")
        or zoho_row.get("reference_number")
        or ""
    )
    date_str = (
        zoho_row.get("date")
        or zoho_row.get("invoice_date")
        or zoho_row.get("bill_date")
        or zoho_row.get("payment_date")
        or ""
    )
    total_str = str(
        zoho_row.get("total")
        or zoho_row.get("amount")
        or zoho_row.get("balance")
        or "0"
    )
    narration = zoho_row.get("notes") or zoho_row.get("description") or f"Zoho Books {tally_type}"
    gst = zoho_row.get("gst_number") or zoho_row.get("gst_no") or ""

    # Line items if present
    line_items = []
    for item in zoho_row.get("line_items", []):
        line_items.append({
            "ledger": item.get("name") or item.get("account_name") or "Sales",
            "amount": str(item.get("item_total") or item.get("amount") or "0"),
            "hsn": item.get("hsn_or_sac") or "",
            "tax_rate": str(item.get("tax_percentage") or "0"),
        })

    # Tax details
    taxes = []
    for t in zoho_row.get("taxes", []):
        taxes.append({
            "ledger": t.get("tax_name") or "GST",
            "amount": str(t.get("tax_amount") or "0"),
        })

    return {
        "voucher_type": tally_type,
        "voucher_number": ref_number,
        "voucher_date": date_str,
        "party_ledger": party,
        "narration": narration[:500],
        "amount": total_str,
        "gst_number": gst,
        "line_items": line_items,
        "taxes": taxes,
        "source": "zoho_books",
        "source_ref": (
            zoho_row.get("invoice_id")
            or zoho_row.get("bill_id")
            or zoho_row.get("payment_id")
            or zoho_row.get("creditnote_id")
            or zoho_row.get("journal_id")
            or ""
        ),
        "raw": zoho_row,  # Tally Gateway can use this for precise mapping
    }


def _derive_narration(voucher_type: str, zoho_row: dict) -> str:
    ref = (
        zoho_row.get("invoice_number")
        or zoho_row.get("payment_number")
        or zoho_row.get("creditnote_number")
        or ""
    )
    party = zoho_row.get("customer_name") or zoho_row.get("vendor_name") or ""
    return f"{voucher_type.replace('_', ' ').title()} {ref} — {party}".strip(" —")


def _extract_amount_str(zoho_row: dict) -> str:
    val = zoho_row.get("total") or zoho_row.get("amount") or zoho_row.get("balance") or "0"
    return str(val)


def _extract_zoho_ref(voucher_type: str, zoho_row: dict) -> str:
    """Unique Zoho Books ID for deduplication (used in unique constraint)."""
    return (
        zoho_row.get("invoice_id")
        or zoho_row.get("bill_id")
        or zoho_row.get("payment_id")
        or zoho_row.get("creditnote_id")
        or zoho_row.get("journal_id")
        or zoho_row.get("transaction_id")
        or f"{voucher_type}:{zoho_row.get('date', '')}:{zoho_row.get('total', '')}"
    )


def _extract_voucher_date(zoho_row: dict) -> datetime:
    raw = (
        zoho_row.get("date")
        or zoho_row.get("invoice_date")
        or zoho_row.get("bill_date")
        or zoho_row.get("payment_date")
        or ""
    )
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass
    return utc_now()


# ---------------------------------------------------------------------------
# Stage vouchers (write TallyStagingVoucher rows, skip duplicates)
# ---------------------------------------------------------------------------

def _stage_vouchers(
    session: Session,
    company_id: int,
    voucher_type: str,
    rows: list[dict],
) -> tuple[int, int]:
    """Write rows to tally_staging_vouchers, skipping already-staged ones.

    Returns (staged_count, skipped_count).
    """
    staged = 0
    skipped = 0
    now = utc_now()

    for row in rows:
        zoho_ref = _extract_zoho_ref(voucher_type, row)
        party = row.get("customer_name") or row.get("vendor_name") or row.get("contact_name")
        narration = _derive_narration(voucher_type, row)
        amount_str = _extract_amount_str(row)
        voucher_date = _extract_voucher_date(row)
        payload = _map_to_tally_payload(voucher_type, row)

        voucher = TallyStagingVoucher(
            company_id=company_id,
            zoho_books_ref=zoho_ref,
            voucher_type=voucher_type,
            voucher_date=voucher_date,
            party_name=party,
            narration=narration[:500],
            amount=amount_str,
            mapped_ledger=payload.get("party_ledger"),
            voucher_data_json=payload,
            status="staged",
            created_at=now,
            updated_at=now,
        )
        session.add(voucher)
        try:
            session.flush()
            staged += 1
        except IntegrityError:
            session.rollback()
            skipped += 1

    return staged, skipped


# ---------------------------------------------------------------------------
# Push one voucher to Tally Gateway
# ---------------------------------------------------------------------------

async def _push_to_tally(voucher: TallyStagingVoucher) -> dict:
    """Send one staging voucher to the Tally Gateway. Returns the gateway response."""
    if not _TALLY_GW_URL:
        return {"status": "gateway_not_configured", "tally_voucher_id": None}

    url = _TALLY_GW_URL.rstrip("/") + "/voucher"
    payload = {
        "voucher_id": voucher.id,
        "company_zoho_ref": voucher.zoho_books_ref,
        "data": voucher.voucher_data_json,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

async def _handle_daily_sync(session: Session, task: AgentTask) -> dict:
    """Pull new Zoho Books transactions and stage them for Tally posting."""
    company_id = task.company_id
    inp = task.input_json or {}

    # Resolve token + org
    try:
        token = _get_books_token(session, company_id)
    except ValueError as e:
        return {"error": str(e), "action": "daily_sync"}

    try:
        org_id = _get_org_id(company_id)
    except ValueError as e:
        return {"error": str(e), "action": "daily_sync"}

    watermark = _get_watermark(session, company_id)
    date_after = watermark.strftime("%Y-%m-%d")
    sync_start = utc_now()

    # Transaction types to pull (can be scoped via input_json)
    tx_types: list[tuple[str, str]] = [
        ("invoices",          "sales_invoice",    "date_after_modified"),
        ("customerpayments",  "receipt",          "date_after_modified"),
        ("bills",             "purchase_invoice", "date_after_modified"),
        ("vendorpayments",    "payment",          "date_after_modified"),
        ("creditnotes",       "credit_note",      "date_after_modified"),
        ("journals",          "journal",          "date_after_modified"),
    ]

    if inp.get("voucher_types"):
        allowed = set(inp["voucher_types"])
        tx_types = [(ep, vt, p) for (ep, vt, p) in tx_types if vt in allowed]

    total_staged = 0
    total_skipped = 0
    type_summary: dict[str, int] = {}

    for endpoint, voucher_type, date_param in tx_types:
        url = f"{_BOOKS_BASE}/{endpoint}"
        params = {
            "organization_id": org_id,
            date_param: date_after,
            "status": "all",
        }
        try:
            rows = await _fetch_books_page(url, params, token)
        except httpx.HTTPStatusError as e:
            logger.warning(
                "[f3_books_sync] %s fetch failed (%s) — skipping type",
                endpoint, e.response.status_code,
            )
            continue
        except Exception as e:
            logger.warning("[f3_books_sync] %s fetch error: %s — skipping type", endpoint, e)
            continue

        if not rows:
            continue

        staged, skipped = _stage_vouchers(session, company_id, voucher_type, rows)
        total_staged += staged
        total_skipped += skipped
        if staged:
            type_summary[voucher_type] = staged

    # Commit all staged vouchers
    try:
        session.commit()
    except Exception as e:
        logger.exception("[f3_books_sync] commit failed after staging: %s", e)
        return {"error": str(e), "action": "daily_sync", "staged": 0}

    # Update watermark to sync_start (not "now" — avoid gap if new txns arrive mid-run)
    _save_watermark(session, company_id, sync_start)

    # ActionLedger — one batch proposal per run (A2, proposed)
    ledger_entry = log_action(
        session=session,
        company_id=company_id,
        agent_name="f3_books_sync",
        action_type="stage_voucher_batch",
        autonomy_level="A2",
        input_data={
            "sync_from": watermark.isoformat(),
            "sync_to": sync_start.isoformat(),
            "org_id": org_id,
            "voucher_types": list(type_summary.keys()),
        },
        output_data={
            "staged_count": total_staged,
            "skipped_duplicates": total_skipped,
            "by_type": type_summary,
        },
        rationale=(
            f"Pulled {total_staged} new transactions from Zoho Books "
            f"({date_after} onward). Staged for accountant review before Tally posting."
        ),
        agent_task_id=task.id,
        entity_type="company",
        entity_id=company_id,
        status="proposed",
    )

    # KPIs
    record_kpi(session, company_id, "f3_books_sync", "staged_vouchers_count", total_staged,
               action_ledger_id=ledger_entry.id if ledger_entry else None)
    record_kpi(session, company_id, "f3_books_sync", "sync_window_hours",
               round((sync_start - watermark).total_seconds() / 3600, 1))

    session.commit()

    result = {
        "action": "daily_sync",
        "staged": total_staged,
        "skipped_duplicates": total_skipped,
        "by_type": type_summary,
        "sync_from": watermark.isoformat(),
        "sync_to": sync_start.isoformat(),
        "ledger_id": ledger_entry.id if ledger_entry else None,
    }
    logger.info("[f3_books_sync] daily_sync: staged=%d skipped=%d", total_staged, total_skipped)
    return result


async def _handle_push_voucher(session: Session, task: AgentTask) -> dict:
    """Post one approved TallyStagingVoucher to the Tally Gateway."""
    company_id = task.company_id
    inp = task.input_json or {}

    staging_id = inp.get("staging_id")
    ledger_id = inp.get("ledger_id")

    if not staging_id:
        return {"error": "staging_id is required for push_voucher"}

    voucher = session.exec(
        select(TallyStagingVoucher).where(
            TallyStagingVoucher.id == staging_id,
            TallyStagingVoucher.company_id == company_id,
        )
    ).first()

    if not voucher:
        return {"error": f"TallyStagingVoucher {staging_id} not found"}

    if voucher.status not in ("approved", "failed"):
        return {
            "error": f"Voucher {staging_id} has status={voucher.status!r} — can only push approved or retrying vouchers",
        }

    # Mark as posting (idempotency guard)
    voucher.status = "posting"
    voucher.updated_at = utc_now()
    session.add(voucher)
    session.commit()

    try:
        gw_response = await _push_to_tally(voucher)
    except httpx.HTTPStatusError as e:
        error_msg = f"Tally Gateway HTTP {e.response.status_code}: {e.response.text[:500]}"
        voucher.status = "failed"
        voucher.error = error_msg
        voucher.retry_count += 1
        voucher.updated_at = utc_now()
        session.add(voucher)
        if ledger_id:
            fail_action(session, ledger_id, error_msg)
        record_kpi(session, company_id, "f3_books_sync", "tally_push_failed", 1,
                   entity_type="tally_staging_voucher", entity_id=staging_id)
        session.commit()
        return {"error": error_msg, "action": "push_voucher", "staging_id": staging_id, "retry_count": voucher.retry_count}
    except Exception as e:
        error_msg = str(e)
        voucher.status = "failed"
        voucher.error = error_msg[:2000]
        voucher.retry_count += 1
        voucher.updated_at = utc_now()
        session.add(voucher)
        if ledger_id:
            fail_action(session, ledger_id, error_msg)
        record_kpi(session, company_id, "f3_books_sync", "tally_push_failed", 1,
                   entity_type="tally_staging_voucher", entity_id=staging_id)
        session.commit()
        return {"error": error_msg, "action": "push_voucher", "staging_id": staging_id}

    gw_status = gw_response.get("status", "")

    if gw_status == "gateway_not_configured":
        # Gateway not yet deployed — revert to approved so accountant sees it's pending
        voucher.status = "approved"
        voucher.updated_at = utc_now()
        session.add(voucher)
        session.commit()
        return {
            "action": "push_voucher",
            "staging_id": staging_id,
            "status": "gateway_not_configured",
            "message": "Tally Gateway not configured (TALLY_GATEWAY_URL env var not set). Set it to enable posting.",
        }

    tally_voucher_id = gw_response.get("tally_voucher_id") or gw_response.get("voucher_id")
    success = bool(tally_voucher_id)

    if success:
        voucher.status = "posted"
        voucher.tally_voucher_id = str(tally_voucher_id)
        voucher.posted_at = utc_now()
        voucher.error = None
        voucher.updated_at = utc_now()
        session.add(voucher)
        if ledger_id:
            complete_action(session, ledger_id, {"tally_voucher_id": tally_voucher_id})
        record_kpi(session, company_id, "f3_books_sync", "tally_posted_count", 1,
                   entity_type="tally_staging_voucher", entity_id=staging_id,
                   metadata={"tally_voucher_id": str(tally_voucher_id)})
        session.commit()
        logger.info("[f3_books_sync] posted staging_id=%d tally_id=%s", staging_id, tally_voucher_id)
        return {
            "action": "push_voucher",
            "staging_id": staging_id,
            "status": "posted",
            "tally_voucher_id": tally_voucher_id,
        }
    else:
        gw_error = gw_response.get("error") or f"Gateway returned: {gw_response}"
        voucher.status = "failed"
        voucher.error = gw_error[:2000]
        voucher.retry_count += 1
        voucher.updated_at = utc_now()
        session.add(voucher)
        if ledger_id:
            fail_action(session, ledger_id, gw_error)
        record_kpi(session, company_id, "f3_books_sync", "tally_push_failed", 1,
                   entity_type="tally_staging_voucher", entity_id=staging_id)
        session.commit()
        return {
            "action": "push_voucher",
            "staging_id": staging_id,
            "status": "failed",
            "error": gw_error,
            "retry_count": voucher.retry_count,
        }


async def _handle_retry_failed(session: Session, task: AgentTask) -> dict:
    """Re-attempt all failed vouchers that haven't hit the retry cap."""
    company_id = task.company_id

    failed_vouchers = session.exec(
        select(TallyStagingVoucher).where(
            TallyStagingVoucher.company_id == company_id,
            TallyStagingVoucher.status == "failed",
            TallyStagingVoucher.retry_count < _MAX_RETRIES,
        ).order_by(TallyStagingVoucher.voucher_date.asc())
    ).all()

    if not failed_vouchers:
        return {"action": "retry_failed", "retried": 0, "message": "No retryable vouchers found."}

    results = []
    for voucher in failed_vouchers:
        # Temporarily set to approved so push_voucher accepts it
        voucher.status = "approved"
        session.add(voucher)
        session.flush()

        retry_task = AgentTask(
            company_id=company_id,
            task_type="push_tally_voucher",
            assigned_agent="f3_books_sync",
            input_json={"action": "push_voucher", "staging_id": voucher.id},
            status="pending",
            priority=2,
        )
        session.add(retry_task)
        results.append({"staging_id": voucher.id, "retry_count": voucher.retry_count + 1})

    session.commit()

    record_kpi(session, company_id, "f3_books_sync", "tally_retry_queued", len(results))
    session.commit()

    logger.info("[f3_books_sync] retry_failed: queued %d vouchers for retry", len(results))
    return {
        "action": "retry_failed",
        "retried": len(results),
        "vouchers": results,
    }


async def _handle_reconcile(session: Session, task: AgentTask) -> dict:
    """Compare Zoho Books total vs Tally posted total; emit drift KPI."""
    company_id = task.company_id
    inp = task.input_json or {}

    # Date range — default: last 30 days
    days = int(inp.get("days", 30))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    # Tally side: sum of posted vouchers in period
    posted_rows = session.exec(
        select(TallyStagingVoucher).where(
            TallyStagingVoucher.company_id == company_id,
            TallyStagingVoucher.status == "posted",
            TallyStagingVoucher.voucher_date >= cutoff,
        )
    ).all()

    tally_total = Decimal("0")
    for v in posted_rows:
        try:
            tally_total += Decimal(v.amount or "0")
        except InvalidOperation:
            pass

    # Zoho Books side: pull receivables report from API
    zoho_total: Optional[Decimal] = None
    zoho_data_available = False
    zoho_error: Optional[str] = None
    try:
        token = _get_books_token(session, company_id)
        org_id = _get_org_id(company_id)
        date_from = cutoff.strftime("%Y-%m-%d")
        date_to = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Zoho Books: sum of all invoices raised in period (gross, before payments)
        url = f"{_BOOKS_BASE}/invoices"
        params = {
            "organization_id": org_id,
            "date_after_modified": date_from,
            "filter_by": "Date.CustomDate",
            "from_date": date_from,
            "to_date": date_to,
        }
        rows = await _fetch_books_page(url, params, token)
        zoho_total = Decimal("0")
        for row in rows:
            try:
                zoho_total += Decimal(str(row.get("total", 0)))
            except InvalidOperation:
                pass
        zoho_data_available = True
    except Exception as e:
        zoho_error = str(e)
        logger.warning("[f3_books_sync] reconcile: Zoho Books fetch failed: %s", e)

    # Only compute drift when both sides have real data
    if zoho_data_available and zoho_total is not None:
        drift = abs(zoho_total - tally_total)
        drift_pct = float(drift / zoho_total * 100) if zoho_total else 0.0
        alert = drift > _DRIFT_ALERT_INR
    else:
        drift = Decimal("0")
        drift_pct = 0.0
        alert = False

    # Pending / failed vouchers breakdown
    pending_count = session.exec(
        select(func.count(TallyStagingVoucher.id)).where(
            TallyStagingVoucher.company_id == company_id,
            TallyStagingVoucher.status.in_(["staged", "pending_approval", "approved"]),
        )
    ).one()
    failed_count = session.exec(
        select(func.count(TallyStagingVoucher.id)).where(
            TallyStagingVoucher.company_id == company_id,
            TallyStagingVoucher.status == "failed",
        )
    ).one()

    ledger_entry = log_action(
        session=session,
        company_id=company_id,
        agent_name="f3_books_sync",
        action_type="reconcile",
        autonomy_level="A3",
        input_data={"days": days, "cutoff": cutoff.isoformat()},
        output_data={
            "zoho_data_available": zoho_data_available,
            "zoho_total_inr": float(zoho_total) if zoho_total is not None else None,
            "tally_total_inr": float(tally_total),
            "drift_inr": float(drift) if zoho_data_available else None,
            "drift_pct": drift_pct if zoho_data_available else None,
            "alert": alert,
            "pending_vouchers": pending_count,
            "failed_vouchers": failed_count,
        },
        rationale=(
            f"Reconciliation over {days}d: Zoho ₹{zoho_total:,.0f} vs Tally ₹{tally_total:,.0f} (drift ₹{drift:,.0f})"
            if zoho_data_available
            else f"Reconciliation over {days}d: Tally posted ₹{tally_total:,.0f}. Zoho Books unavailable: {zoho_error}"
        ),
        agent_task_id=task.id,
        entity_type="company",
        entity_id=company_id,
        status="auto_executed",
    )

    if zoho_data_available:
        record_kpi(session, company_id, "f3_books_sync", "tally_sync_drift_inr", str(drift),
                   action_ledger_id=ledger_entry.id if ledger_entry else None)
        record_kpi(session, company_id, "f3_books_sync", "tally_sync_drift_pct", str(round(drift_pct, 2)))

    session.commit()

    logger.info(
        "[f3_books_sync] reconcile: zoho_available=%s zoho=₹%s tally=₹%.0f drift=₹%s alert=%s",
        zoho_data_available,
        f"{zoho_total:,.0f}" if zoho_total is not None else "N/A",
        tally_total,
        f"{drift:,.0f}" if zoho_data_available else "N/A",
        alert,
    )
    return {
        "action": "reconcile",
        "days": days,
        "zoho_data_available": zoho_data_available,
        "zoho_error": zoho_error,
        "zoho_total_inr": float(zoho_total) if zoho_total is not None else None,
        "tally_total_inr": float(tally_total),
        "drift_inr": float(drift) if zoho_data_available else None,
        "drift_pct": round(drift_pct, 2) if zoho_data_available else None,
        "alert": alert,
        "alert_threshold_inr": float(_DRIFT_ALERT_INR),
        "pending_vouchers": pending_count,
        "failed_vouchers": failed_count,
        "ledger_id": ledger_entry.id if ledger_entry else None,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def run(session: Session, task: AgentTask) -> dict:
    """Dispatch to the appropriate F3 Books-Sync action."""
    action = (task.input_json or {}).get("action")
    try:
        if action == "daily_sync":
            return await _handle_daily_sync(session, task)
        elif action == "push_voucher":
            return await _handle_push_voucher(session, task)
        elif action == "retry_failed":
            return await _handle_retry_failed(session, task)
        elif action == "reconcile":
            return await _handle_reconcile(session, task)
        else:
            return {
                "error": f"Unknown action: {action!r}",
                "valid_actions": ["daily_sync", "push_voucher", "retry_failed", "reconcile"],
            }
    except Exception as exc:
        logger.exception("[f3_books_sync] action=%s failed: %s", action, exc)
        return {"error": str(exc), "action": action}

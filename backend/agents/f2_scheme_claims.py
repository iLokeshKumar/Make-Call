"""
F2 Scheme Claims Agent — Vendor promotional incentive claim computation.

Vendors run monthly/quarterly scheme PDFs covering:
  volume_incentive   Sell N+ units in the period → earn rate_per_unit (slab-based)
  model_incentive    Sell specific SKUs → flat rate per unit
  display_incentive  Maintain active display at dealers → flat amount per scheme
  mdf                Market development fund → flat amount for territory promotions

The finance team enters scheme rules into vendor_schemes once per scheme PDF.
F2 then:
  1. Scans qualifying invoices against active schemes (daily_scan)
  2. Computes claim workings per scheme: units × rate, slab selection, serial evidence
  3. Drafts a SchemeClaim with full SchemeClaimLine breakdown
  4. Proposes to Finance Manager via ActionLedger at A1 (never auto-submits)

The Finance Manager reviews the workings line-by-line before approving submission
to the vendor, because a wrong claim: (a) gets deducted from future settlements,
(b) damages the distributor relationship, (c) is hard to reverse.

Actions
-------
daily_scan      Check all active schemes for qualifying invoices; create/refresh
                SchemeClaim drafts; propose via ActionLedger where units > min_qty.
draft_claim     (Re)compute one specific scheme's claim workings on demand.
record_settlement  Record the vendor's settlement against a submitted claim;
                   compute accuracy_pct; emit scheme_claim_accuracy KPI.
compute_accuracy   Aggregate accuracy across all settled claims in a window.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlmodel import Session, select

from models.models import (
    AgentTask,
    Invoice,
    InvoiceItem,
    Lead,
    Product,
    VendorScheme,
    SchemeClaim,
    SchemeClaimLine,
    SerialRegistry,
    utc_now,
)
from services.action_ledger import log_action, record_kpi

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Incentive computation
# ---------------------------------------------------------------------------

def _compute_volume_incentive(rules: dict, total_units: int) -> Decimal:
    """Apply slab-based volume incentive.

    rules format:
      [{"min_qty": 0, "max_qty": 49, "rate_per_unit": 300},
       {"min_qty": 50, "max_qty": null, "rate_per_unit": 500}]

    The highest slab the total_units qualifies for applies to ALL units.
    (All-or-nothing slab model: the highest qualifying tier applies to ALL units.)
    """
    if not isinstance(rules, list) or total_units == 0:
        return Decimal("0")

    applicable_rate = Decimal("0")
    for slab in rules:
        min_q = int(slab.get("min_qty", 0))
        max_q = slab.get("max_qty")  # None = unlimited
        rate = Decimal(str(slab.get("rate_per_unit", 0)))
        if total_units >= min_q and (max_q is None or total_units <= int(max_q)):
            applicable_rate = rate
            # Don't break — take the last matching slab (highest qualifying tier)

    return (applicable_rate * total_units).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_model_incentive(rules: dict, total_units: int) -> Decimal:
    """Flat rate per unit. rules: {"rate_per_unit": 800}"""
    rate = Decimal(str(rules.get("rate_per_unit", 0)))
    return (rate * total_units).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_flat_incentive(rules: dict) -> Decimal:
    """Flat amount regardless of volume. rules: {"flat_amount": 25000}"""
    return Decimal(str(rules.get("flat_amount", 0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _compute_claim_amount(scheme: VendorScheme, total_units: int) -> Decimal:
    rules = scheme.incentive_rules
    if scheme.scheme_type == "volume_incentive":
        return _compute_volume_incentive(rules, total_units)
    elif scheme.scheme_type == "model_incentive":
        return _compute_model_incentive(rules, total_units)
    elif scheme.scheme_type in ("display_incentive", "mdf"):
        return _compute_flat_incentive(rules)
    return Decimal("0")


def _rate_per_unit_for_line(scheme: VendorScheme, total_units: int) -> Decimal:
    """Effective per-unit rate for claim line display (flat schemes show flat/units)."""
    if total_units == 0:
        return Decimal("0")
    total = _compute_claim_amount(scheme, total_units)
    return (total / total_units).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Product eligibility
# ---------------------------------------------------------------------------

def _is_product_eligible(product: Product, scheme: VendorScheme) -> bool:
    """True if the product falls within the scheme's eligibility filters."""
    brands = [b.lower() for b in scheme.eligible_brands]
    categories = [c.lower() for c in scheme.eligible_categories]
    skus = [s.upper() for s in scheme.eligible_skus]

    if brands and (not product.brand or product.brand.lower() not in brands):
        return False
    if categories and (not product.category or product.category.lower() not in categories):
        return False
    if skus and (not product.sku or product.sku.upper() not in skus):
        return False
    return True


# ---------------------------------------------------------------------------
# Invoice + serial evidence gathering
# ---------------------------------------------------------------------------

def _gather_qualifying_lines(
    session: Session,
    company_id: int,
    scheme: VendorScheme,
) -> list[dict]:
    """Return list of qualifying invoice×product groups within the scheme window.

    Each dict:
      invoice_id, invoice_number, invoice_date, lead_id,
      product_id, sku_snapshot, product_name_snapshot,
      quantity, serial_numbers
    """
    period_start = scheme.period_start
    period_end = scheme.period_end

    # Pull all invoices in the scheme period (sent/paid — only dispatched goods count)
    qualifying_invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == company_id,
            Invoice.status.in_(["sent", "partially_paid", "paid"]),
            Invoice.sent_at >= period_start,
            Invoice.sent_at <= period_end,
        )
    ).all()

    if not qualifying_invoices:
        return []

    invoice_ids = [inv.id for inv in qualifying_invoices]
    invoice_map = {inv.id: inv for inv in qualifying_invoices}

    # Pull invoice items for those invoices
    items = session.exec(
        select(InvoiceItem).where(
            InvoiceItem.invoice_id.in_(invoice_ids),
            InvoiceItem.company_id == company_id,
        )
    ).all()

    # Load products for eligibility check
    product_ids = {item.order_item_id for item in items if item.order_item_id}
    # InvoiceItem doesn't have product_id directly — resolve via description/sku match
    # or pull from OrderItem if linked. We use a join approach via sku_snapshot.

    # Build product lookup: sku → Product
    all_products = session.exec(
        select(Product).where(
            Product.company_id == company_id,
            Product.brand.isnot(None),
        )
    ).all()
    sku_to_product: dict[str, Product] = {}
    for p in all_products:
        if p.sku:
            sku_to_product[p.sku.upper()] = p

    # Group items by (invoice_id, product/sku)
    groups: dict[tuple, dict] = {}
    for item in items:
        invoice = invoice_map.get(item.invoice_id)
        if not invoice:
            continue

        # Resolve product: try sku_snapshot on item (InvoiceItem has no sku_snapshot directly —
        # use description as name proxy; link via order_item_id to OrderItem if available)
        product: Optional[Product] = None
        sku_key: Optional[str] = None

        # Try to find product by matching description against known SKUs/names
        for p in all_products:
            desc_lower = (item.description or "").lower()
            if p.sku and p.sku.lower() in desc_lower:
                product = p
                sku_key = p.sku.upper()
                break
            if p.name.lower() in desc_lower:
                product = p
                sku_key = p.sku.upper() if p.sku else None
                break

        if product and not _is_product_eligible(product, scheme):
            continue
        if not product and scheme.eligible_skus:
            continue  # strict SKU scheme — skip unresolved items

        key = (item.invoice_id, sku_key or item.description[:50])
        if key not in groups:
            groups[key] = {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.sent_at or invoice.created_at,
                "lead_id": invoice.lead_id,
                "product_id": product.id if product else None,
                "sku_snapshot": sku_key,
                "product_name_snapshot": product.name if product else item.description[:200],
                "quantity": 0,
                "serial_numbers": [],
            }
        groups[key]["quantity"] += item.quantity

    # Enrich with serial numbers from SerialRegistry (serial evidence for claim verification)
    for key, group in groups.items():
        if not group["product_id"]:
            continue
        serials = session.exec(
            select(SerialRegistry).where(
                SerialRegistry.company_id == company_id,
                SerialRegistry.product_id == group["product_id"],
                SerialRegistry.allocated_to_lead_id == group["lead_id"],
                SerialRegistry.status.in_(["dispatched", "sold"]),
                SerialRegistry.dispatched_at >= period_start,
                SerialRegistry.dispatched_at <= period_end,
            )
        ).all()
        group["serial_numbers"] = [s.serial_number for s in serials]
        # Reconcile quantity: serial count is ground truth if serials exist
        if serials:
            group["quantity"] = len(serials)

    return [g for g in groups.values() if g["quantity"] > 0]


# ---------------------------------------------------------------------------
# Claim computation
# ---------------------------------------------------------------------------

def _build_claim(
    session: Session,
    company_id: int,
    scheme: VendorScheme,
    task_id: Optional[int] = None,
) -> Optional[SchemeClaim]:
    """Compute or refresh one SchemeClaim for a scheme.

    If a draft/proposed claim already exists for this scheme+period,
    refreshes its workings in place.
    Returns None if no qualifying units found.
    """
    now = utc_now()
    lines_data = _gather_qualifying_lines(session, company_id, scheme)

    # Flat schemes (display_incentive, mdf) don't count units per invoice
    is_flat = scheme.scheme_type in ("display_incentive", "mdf")

    if is_flat:
        total_units = 1  # flat schemes earn once per scheme period
        total_amount = _compute_flat_incentive(scheme.incentive_rules)
        lines_data = []  # no per-invoice breakdown for flat schemes
    else:
        total_units = sum(g["quantity"] for g in lines_data)
        if total_units < scheme.min_quantity:
            logger.info(
                "[F2] scheme=%s: %d units < min %d — no claim",
                scheme.scheme_code, total_units, scheme.min_quantity,
            )
            return None
        total_amount = _compute_claim_amount(scheme, total_units)

    if total_amount <= Decimal("0"):
        return None

    # Check for existing editable claim
    existing = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.company_id == company_id,
            SchemeClaim.scheme_id == scheme.id,
            SchemeClaim.claim_period_start == scheme.period_start,
            SchemeClaim.status.in_(["draft", "proposed"]),
        )
    ).first()

    # Build workings snapshot
    effective_rate = _rate_per_unit_for_line(scheme, total_units)
    by_product: dict[str, dict] = {}
    for g in lines_data:
        key = g["sku_snapshot"] or g["product_name_snapshot"]
        if key not in by_product:
            by_product[key] = {"quantity": 0, "invoices": [], "serial_count": 0}
        by_product[key]["quantity"] += g["quantity"]
        by_product[key]["invoices"].append(g["invoice_number"])
        by_product[key]["serial_count"] += len(g["serial_numbers"])

    workings = {
        "scheme_code": scheme.scheme_code,
        "scheme_type": scheme.scheme_type,
        "period": {
            "start": scheme.period_start.isoformat(),
            "end": scheme.period_end.isoformat(),
        },
        "total_qualifying_units": total_units,
        "effective_rate_per_unit": float(effective_rate),
        "total_claimed_inr": float(total_amount),
        "by_product": by_product,
        "incentive_rules": scheme.incentive_rules,
    }

    if existing:
        existing.total_qualifying_units = total_units
        existing.total_claimed_inr = total_amount
        existing.claim_workings = workings
        existing.updated_at = now
        session.add(existing)
        session.flush()
        claim = existing
        # Refresh claim lines
        old_lines = session.exec(
            select(SchemeClaimLine).where(SchemeClaimLine.claim_id == claim.id)
        ).all()
        for line in old_lines:
            session.delete(line)
        session.flush()
    else:
        claim = SchemeClaim(
            company_id=company_id,
            scheme_id=scheme.id,
            claim_period_start=scheme.period_start,
            claim_period_end=scheme.period_end,
            total_qualifying_units=total_units,
            total_claimed_inr=total_amount,
            status="draft",
            agent_task_id=task_id,
            claim_workings=workings,
            created_at=now,
            updated_at=now,
        )
        session.add(claim)
        session.flush()

    # Write claim lines (per invoice×product)
    for g in lines_data:
        line_qty = g["quantity"]
        line_rate = effective_rate
        line_amount = (line_rate * line_qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        line = SchemeClaimLine(
            company_id=company_id,
            claim_id=claim.id,
            invoice_id=g["invoice_id"],
            product_id=g["product_id"],
            lead_id=g["lead_id"],
            sku_snapshot=g["sku_snapshot"],
            product_name_snapshot=g["product_name_snapshot"],
            invoice_number=g["invoice_number"],
            invoice_date=g["invoice_date"],
            quantity=line_qty,
            rate_per_unit=line_rate,
            line_amount=line_amount,
            serial_numbers=g["serial_numbers"],
            created_at=now,
        )
        session.add(line)

    session.flush()
    return claim


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_daily_scan(session: Session, task: AgentTask) -> dict:
    """Scan all active schemes; create/refresh claim drafts; propose via ActionLedger."""
    company_id = task.company_id
    now = datetime.now(timezone.utc)

    active_schemes = session.exec(
        select(VendorScheme).where(
            VendorScheme.company_id == company_id,
            VendorScheme.status == "active",
            VendorScheme.period_end >= now,
        )
    ).all()

    if not active_schemes:
        return {
            "action": "daily_scan",
            "message": "No active schemes found. Add schemes via /crm/scheme-claims/schemes.",
            "schemes_checked": 0,
            "claims_drafted": 0,
        }

    drafted: list[dict] = []
    skipped: list[dict] = []

    for scheme in active_schemes:
        claim = _build_claim(session, company_id, scheme, task_id=task.id)

        if claim is None:
            skipped.append({
                "scheme_code": scheme.scheme_code,
                "reason": f"Units below minimum ({scheme.min_quantity}) or ₹0 computed",
            })
            continue

        # Log ActionLedger proposal (A1 — always individual review)
        ledger_entry = log_action(
            session=session,
            company_id=company_id,
            agent_name="f2_scheme_claims",
            action_type="propose_scheme_claim",
            autonomy_level="A1",
            input_data={
                "scheme_id": scheme.id,
                "scheme_code": scheme.scheme_code,
                "scheme_type": scheme.scheme_type,
                "period_start": scheme.period_start.isoformat(),
                "period_end": scheme.period_end.isoformat(),
                "submission_deadline": scheme.submission_deadline.isoformat()
                    if scheme.submission_deadline else None,
            },
            output_data={
                "claim_id": claim.id,
                "total_qualifying_units": claim.total_qualifying_units,
                "total_claimed_inr": float(claim.total_claimed_inr),
                "claim_workings": claim.claim_workings,
            },
            rationale=(
                f"Scheme '{scheme.scheme_name}' ({scheme.scheme_code}): "
                f"{claim.total_qualifying_units} qualifying unit(s) → "
                f"₹{float(claim.total_claimed_inr):,.0f} claimable. "
                f"Requires Finance Manager approval before submission to vendor."
            ),
            agent_task_id=task.id,
            entity_type="vendor_scheme",
            entity_id=scheme.id,
            status="proposed",
        )

        # Link ledger back to claim
        claim.action_ledger_id = ledger_entry.id if ledger_entry else None
        claim.status = "proposed"
        claim.updated_at = utc_now()
        session.add(claim)

        record_kpi(
            session, company_id, "f2_scheme_claims", "scheme_claim_value_inr",
            float(claim.total_claimed_inr),
            entity_type="vendor_scheme", entity_id=scheme.id,
            action_ledger_id=ledger_entry.id if ledger_entry else None,
            metadata={"scheme_code": scheme.scheme_code, "units": claim.total_qualifying_units},
        )

        drafted.append({
            "scheme_code": scheme.scheme_code,
            "claim_id": claim.id,
            "ledger_id": ledger_entry.id if ledger_entry else None,
            "total_units": claim.total_qualifying_units,
            "total_claimed_inr": float(claim.total_claimed_inr),
        })

    session.commit()

    total_value = sum(d["total_claimed_inr"] for d in drafted)
    logger.info(
        "[F2] daily_scan: company=%d drafted=%d total=₹%.0f skipped=%d",
        company_id, len(drafted), total_value, len(skipped),
    )
    return {
        "action": "daily_scan",
        "schemes_checked": len(active_schemes),
        "claims_drafted": len(drafted),
        "claims_skipped": len(skipped),
        "total_claimable_inr": total_value,
        "drafted": drafted,
        "skipped": skipped,
    }


def _handle_draft_claim(session: Session, task: AgentTask) -> dict:
    """(Re)compute workings for one specific scheme on demand."""
    company_id = task.company_id
    inp = task.input_json or {}
    scheme_id = inp.get("scheme_id")

    if not scheme_id:
        return {"error": "scheme_id is required for draft_claim"}

    scheme = session.exec(
        select(VendorScheme).where(
            VendorScheme.id == scheme_id,
            VendorScheme.company_id == company_id,
        )
    ).first()
    if not scheme:
        return {"error": f"VendorScheme {scheme_id} not found"}

    claim = _build_claim(session, company_id, scheme, task_id=task.id)
    if claim is None:
        return {
            "action": "draft_claim",
            "scheme_id": scheme_id,
            "scheme_code": scheme.scheme_code,
            "total_units": 0,
            "total_claimed_inr": 0,
            "message": f"No qualifying units found above minimum ({scheme.min_quantity}).",
        }

    session.commit()
    logger.info("[F2] draft_claim: scheme=%s claim_id=%d ₹%.0f",
                scheme.scheme_code, claim.id, float(claim.total_claimed_inr))
    return {
        "action": "draft_claim",
        "scheme_id": scheme_id,
        "scheme_code": scheme.scheme_code,
        "claim_id": claim.id,
        "total_units": claim.total_qualifying_units,
        "total_claimed_inr": float(claim.total_claimed_inr),
        "status": claim.status,
        "workings": claim.claim_workings,
    }


def _handle_record_settlement(session: Session, task: AgentTask) -> dict:
    """Record vendor's settlement against a submitted claim; compute accuracy KPI.

    Required input_json:
        claim_id          — SchemeClaim.id
        settled_amount_inr — amount vendor actually credited
        settlement_ref    — vendor settlement reference number
        settled_date      — ISO date string
    """
    company_id = task.company_id
    inp = task.input_json or {}

    claim_id = inp.get("claim_id")
    settled_amount = inp.get("settled_amount_inr")
    settlement_ref = inp.get("settlement_ref", "")
    settled_date_str = inp.get("settled_date")

    if not claim_id or settled_amount is None:
        return {"error": "claim_id and settled_amount_inr are required for record_settlement"}

    claim = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.id == claim_id,
            SchemeClaim.company_id == company_id,
        )
    ).first()
    if not claim:
        return {"error": f"SchemeClaim {claim_id} not found"}
    if claim.status not in ("submitted", "acknowledged"):
        return {
            "error": f"Claim {claim_id} is in status '{claim.status}' — "
                     "only submitted/acknowledged claims can be settled",
        }

    settled = Decimal(str(settled_amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    claimed = claim.total_claimed_inr
    variance = settled - claimed
    accuracy = (
        (Decimal("100") - abs(variance) / claimed * Decimal("100"))
        .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if claimed > Decimal("0")
        else Decimal("0")
    )

    settled_dt = (
        datetime.fromisoformat(settled_date_str).replace(tzinfo=timezone.utc)
        if settled_date_str
        else utc_now()
    )

    claim.settled_amount_inr = settled
    claim.variance_inr = variance
    claim.accuracy_pct = accuracy
    claim.status = "settled"
    claim.settled_at = settled_dt
    if settlement_ref:
        claim.submission_ref = settlement_ref
    claim.updated_at = utc_now()
    session.add(claim)

    # Log settlement in ActionLedger
    ledger_entry = log_action(
        session=session,
        company_id=company_id,
        agent_name="f2_scheme_claims",
        action_type="record_settlement",
        autonomy_level="A3",
        input_data={
            "claim_id": claim_id,
            "settlement_ref": settlement_ref,
            "settled_date": settled_dt.isoformat(),
        },
        output_data={
            "claimed_inr": float(claimed),
            "settled_inr": float(settled),
            "variance_inr": float(variance),
            "accuracy_pct": float(accuracy),
        },
        rationale=(
            f"Claim {claim_id} settled at ₹{float(settled):,.0f} "
            f"(claimed ₹{float(claimed):,.0f}, variance ₹{float(variance):+,.0f}, "
            f"accuracy {float(accuracy):.1f}%)"
        ),
        agent_task_id=task.id,
        entity_type="vendor_scheme",
        entity_id=claim.scheme_id,
        status="auto_executed",
    )

    record_kpi(
        session, company_id, "f2_scheme_claims", "scheme_claim_accuracy",
        float(accuracy),
        entity_type="scheme_claim", entity_id=claim_id,
        action_ledger_id=ledger_entry.id if ledger_entry else None,
        metadata={
            "claim_id": claim_id,
            "variance_inr": float(variance),
            "settled_inr": float(settled),
        },
    )

    session.commit()

    logger.info(
        "[F2] record_settlement: claim=%d settled=₹%.0f accuracy=%.1f%%",
        claim_id, float(settled), float(accuracy),
    )
    return {
        "action": "record_settlement",
        "claim_id": claim_id,
        "claimed_inr": float(claimed),
        "settled_inr": float(settled),
        "variance_inr": float(variance),
        "accuracy_pct": float(accuracy),
        "status": "settled",
    }


def _handle_compute_accuracy(session: Session, task: AgentTask) -> dict:
    """Aggregate scheme_claim_accuracy across all settled claims in a window."""
    from datetime import timedelta
    company_id = task.company_id
    inp = task.input_json or {}
    days = int(inp.get("days", 90))
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    settled_claims = session.exec(
        select(SchemeClaim).where(
            SchemeClaim.company_id == company_id,
            SchemeClaim.status == "settled",
            SchemeClaim.settled_at >= cutoff,
            SchemeClaim.accuracy_pct.isnot(None),
        )
    ).all()

    if not settled_claims:
        return {
            "action": "compute_accuracy",
            "days": days,
            "settled_claims": 0,
            "avg_accuracy_pct": None,
            "message": "No settled claims in window.",
        }

    accuracy_values = [float(c.accuracy_pct) for c in settled_claims if c.accuracy_pct is not None]
    avg_accuracy = round(sum(accuracy_values) / len(accuracy_values), 2)
    meets_a2_gate = avg_accuracy >= 97.0

    ledger_entry = log_action(
        session=session,
        company_id=company_id,
        agent_name="f2_scheme_claims",
        action_type="accuracy_report",
        autonomy_level="A3",
        input_data={"days": days, "cutoff": cutoff.isoformat()},
        output_data={
            "settled_count": len(settled_claims),
            "avg_accuracy_pct": avg_accuracy,
            "meets_a2_gate": meets_a2_gate,
            "per_claim": [
                {"claim_id": c.id, "accuracy_pct": float(c.accuracy_pct)}
                for c in settled_claims
            ],
        },
        rationale=(
            f"{len(settled_claims)} settled claim(s) over {days}d: "
            f"avg accuracy {avg_accuracy:.1f}% "
            f"({'✓ meets A2 gate' if meets_a2_gate else '✗ below 97% A2 gate'})"
        ),
        agent_task_id=task.id,
        entity_type="company",
        entity_id=company_id,
        status="auto_executed",
    )

    record_kpi(
        session, company_id, "f2_scheme_claims", "scheme_claim_accuracy_avg",
        avg_accuracy,
        action_ledger_id=ledger_entry.id if ledger_entry else None,
        metadata={"days": days, "settled_count": len(settled_claims)},
    )

    session.commit()

    logger.info(
        "[F2] compute_accuracy: avg=%.1f%% settled=%d meets_a2=%s",
        avg_accuracy, len(settled_claims), meets_a2_gate,
    )
    return {
        "action": "compute_accuracy",
        "days": days,
        "settled_claims": len(settled_claims),
        "avg_accuracy_pct": avg_accuracy,
        "meets_a2_gate": meets_a2_gate,
        "a2_gate_threshold_pct": 97.0,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_VALID_ACTIONS = frozenset([
    "daily_scan", "draft_claim", "record_settlement", "compute_accuracy",
])


async def run(session: Session, task: AgentTask) -> dict:
    """Dispatch to the appropriate F2 action."""
    action = (task.input_json or {}).get("action")
    if action not in _VALID_ACTIONS:
        return {
            "error": f"Unknown action: {action!r}",
            "valid_actions": sorted(_VALID_ACTIONS),
        }
    try:
        if action == "daily_scan":
            return _handle_daily_scan(session, task)
        elif action == "draft_claim":
            return _handle_draft_claim(session, task)
        elif action == "record_settlement":
            return _handle_record_settlement(session, task)
        elif action == "compute_accuracy":
            return _handle_compute_accuracy(session, task)
    except Exception as exc:
        logger.exception("[F2] action=%s failed: %s", action, exc)
        return {"error": str(exc), "action": action}

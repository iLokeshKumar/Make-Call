from __future__ import annotations

import hashlib
import logging
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import (
    Lead,
    LeadRequirement,
    LeadRequirementUpsert,
    Product,
    ProposalDocument,
    ProposalRequest,
    Quote,
    QuoteCreate,
    QuoteItemCreate,
    utc_now,
)
from services.requirement_service import get_latest_requirements, upsert_lead_requirements

logger = logging.getLogger(__name__)

_INTENT_TERMS = {
    "rfp": ["rfp", "request for proposal", "tender", "bid"],
    "rfq": ["rfq", "request for quotation", "quotation", "quote", "pricing", "price", "estimate"],
    "proposal": ["proposal", "commercial offer", "solution document"],
}

_QTY_RE = re.compile(r"(?P<qty>\d+)\s*(?P<unit>pcs|pieces|units|nos|sets|boxes|licenses)?\s+(?P<item>[a-zA-Z0-9][^,;\n]{2,80})")


def _decimal_str(value: Decimal | int | float | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _extract_intent(text: str | None) -> tuple[str, Decimal]:
    normalized = (text or "").lower()
    best = "quote"
    hits = 0
    for intent, terms in _INTENT_TERMS.items():
        count = sum(1 for term in terms if term in normalized)
        if count > hits:
            best = intent
            hits = count
    confidence = Decimal("0.25") if hits == 0 else min(Decimal("0.95"), Decimal("0.55") + Decimal("0.15") * hits)
    return best, confidence


def _extract_quantity_items(text: str | None) -> list[dict[str, Any]]:
    if not text:
        return []
    items: list[dict[str, Any]] = []
    for match in _QTY_RE.finditer(text):
        item = re.sub(r"\b(of|for|with|and)$", "", match.group("item").strip(), flags=re.I).strip()
        if item:
            items.append({
                "item": item,
                "quantity": int(match.group("qty")),
                "unit": match.group("unit") or "unit",
                "source": "request_text",
            })
    return items[:10]


def _latest_interaction_text(session: Session, company_id: int, lead_id: int, interaction_id: int | None) -> str | None:
    from models.models import Interaction

    query = select(Interaction).where(
        Interaction.company_id == company_id,
        Interaction.lead_id == lead_id,
    )
    if interaction_id is not None:
        query = query.where(Interaction.id == interaction_id)
    row = session.exec(query.order_by(Interaction.created_at.desc()).limit(1)).first()
    if not row:
        return None
    return row.transcript or row.content


def _requirement_to_spec(requirement: LeadRequirement | None, request_text: str | None, intent: str, confidence: Decimal) -> dict[str, Any]:
    structured = dict(requirement.structured_data or {}) if requirement else {}
    quantities = structured.get("quantities") or _extract_quantity_items(request_text)
    required_products = structured.get("required_products") or (requirement.required_products if requirement else None)
    missing_fields = []
    if not required_products and not quantities:
        missing_fields.append("required_products")
    if not (structured.get("delivery_location") or structured.get("city")):
        missing_fields.append("delivery_location")
    if not (structured.get("timeline") or (requirement.timeline if requirement else None)):
        missing_fields.append("timeline")

    return {
        "intent": intent,
        "intent_confidence": float(confidence),
        "buyer_problem": structured.get("buyer_problem") or (requirement.use_case if requirement else None),
        "required_products": required_products,
        "quantities": quantities,
        "technical_constraints": structured.get("technical_constraints") or [],
        "delivery_location": structured.get("delivery_location") or structured.get("city"),
        "timeline": structured.get("timeline") or (requirement.timeline if requirement else None),
        "budget_range": structured.get("budget_range") or (requirement.budget_range if requirement else None),
        "decision_criteria": structured.get("decision_criteria") or [],
        "competitors": requirement.competitors if requirement else structured.get("competitors"),
        "pain_points": requirement.pain_points if requirement else structured.get("pain_points"),
        "missing_fields": missing_fields,
        "evidence": [
            {"field": "intent", "source": "request_text", "confidence": float(confidence)},
        ],
    }


def _candidate_terms(spec: dict[str, Any]) -> list[str]:
    terms: list[str] = []
    req_products = spec.get("required_products")
    if isinstance(req_products, str):
        terms.extend([p.strip() for p in re.split(r"[,;\n]+", req_products) if p.strip()])
    elif isinstance(req_products, list):
        terms.extend(str(p).strip() for p in req_products if str(p).strip())
    for q in spec.get("quantities") or []:
        item = q.get("item") if isinstance(q, dict) else None
        if item:
            terms.append(str(item))
    return terms


def _score_product(product: Product, term: str) -> int:
    term_l = term.lower().strip()
    if not term_l:
        return 0
    fields = [
        product.name or "",
        product.sku or "",
        product.brand or "",
        product.category or "",
        product.subcategory or "",
        product.model_number or "",
        product.description or "",
    ]
    haystack = " ".join(fields).lower()
    score = 0
    if product.sku and term_l == product.sku.lower():
        score += 120
    if product.name and term_l == product.name.lower():
        score += 100
    if product.name and term_l in product.name.lower():
        score += 55
    if term_l in haystack:
        score += 35
    for token in re.split(r"[\s\-_/]+", term_l):
        if len(token) >= 3 and token in haystack:
            score += 6
    return score


def _match_products(session: Session, company_id: int, spec: dict[str, Any]) -> list[dict[str, Any]]:
    terms = _candidate_terms(spec)
    products = session.exec(
        select(Product).where(Product.company_id == company_id, Product.is_active == True)  # noqa: E712
    ).all()
    matches: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    for term in terms:
        ranked = sorted(
            ((p, _score_product(p, term)) for p in products),
            key=lambda pair: pair[1],
            reverse=True,
        )
        if not ranked or ranked[0][1] < 35:
            matches.append({"requested": term, "matched": None, "reason": "no_confident_catalog_match"})
            continue
        product, score = ranked[0]
        if product.id in used_ids:
            continue
        used_ids.add(product.id)
        qty = 1
        for q in spec.get("quantities") or []:
            if isinstance(q, dict) and str(q.get("item", "")).lower() in term.lower():
                qty = int(q.get("quantity") or 1)
        matches.append({
            "requested": term,
            "matched": {
                "product_id": product.id,
                "name": product.name,
                "sku": product.sku,
                "quantity": qty,
                "unit_price": _decimal_str(product.price),
                "currency": product.currency,
                "stock": product.stock,
                "min_price": _decimal_str(product.min_price),
                "tax_rate": _decimal_str(product.tax_rate),
                "score": score,
            },
            "reason": "catalog_match",
        })
    return matches


def _build_solution_context(company_id: int, spec: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        from services.rag.query_engine import search
        query = " ".join(str(t) for t in _candidate_terms(spec)) or str(spec.get("buyer_problem") or "")
        if not query.strip():
            return []
        return search(query, company_id=company_id, collection="all", n_results=5)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[proposal] RAG context unavailable: %s", exc)
        return []


def _build_solution(session: Session, company_id: int, spec: dict[str, Any]) -> dict[str, Any]:
    matches = _match_products(session, company_id, spec)
    context = _build_solution_context(company_id, spec)
    assumptions = []
    if spec.get("missing_fields"):
        assumptions.append("Some requirement fields are missing; proposal should remain draft until clarified.")
    if not any(m.get("matched") for m in matches):
        assumptions.append("No confident catalog match found; manual solution review required.")
    return {
        "recommended_items": matches,
        "knowledge_context": [
            {
                "collection": r.get("collection"),
                "title": (r.get("metadata") or {}).get("title"),
                "score": r.get("score"),
                "content_preview": str(r.get("content") or "")[:500],
            }
            for r in context
        ],
        "assumptions": assumptions,
        "alternatives": [],
    }


def _quote_items_from_solution(solution: dict[str, Any]) -> list[QuoteItemCreate]:
    items: list[QuoteItemCreate] = []
    for rec in solution.get("recommended_items") or []:
        match = rec.get("matched")
        if not match:
            continue
        unit_price = Decimal(str(match.get("unit_price") or "0.00"))
        items.append(
            QuoteItemCreate(
                product_id=match.get("product_id"),
                product_name_snapshot=match.get("name") or rec.get("requested") or "Proposal item",
                sku_snapshot=match.get("sku"),
                quantity=max(1, int(match.get("quantity") or 1)),
                unit_price=unit_price,
                discount_percent=Decimal("0.00"),
            )
        )
    return items


def _validate_solution_and_quote(
    session: Session,
    company_id: int,
    spec: dict[str, Any],
    solution: dict[str, Any],
    quote: Quote | None,
) -> dict[str, Any]:
    warnings: list[str] = []
    blockers: list[str] = []

    for field in spec.get("missing_fields") or []:
        warnings.append(f"Missing requirement field: {field}")

    unmatched = [r.get("requested") for r in solution.get("recommended_items") or [] if not r.get("matched")]
    if unmatched:
        blockers.append(f"No catalog match for: {', '.join(str(x) for x in unmatched[:5])}")

    if quote is None:
        blockers.append("No quote draft was created.")
    else:
        quote_items = session.exec(select(Quote).where(Quote.id == quote.id, Quote.company_id == company_id)).first()
        if not quote_items:
            blockers.append("Quote draft could not be reloaded.")
        if quote.total_amount <= 0:
            blockers.append("Quote total is zero.")
        if quote.valid_until is None:
            warnings.append("Quote has no validity date.")

    for rec in solution.get("recommended_items") or []:
        match = rec.get("matched")
        if not match:
            continue
        qty = int(match.get("quantity") or 1)
        stock = match.get("stock")
        if stock is not None and int(stock) < qty:
            warnings.append(f"Stock warning for {match.get('name')}: requested {qty}, stock {stock}.")
        min_price = match.get("min_price")
        unit_price = match.get("unit_price")
        if min_price is not None and unit_price is not None and Decimal(str(unit_price)) < Decimal(str(min_price)):
            blockers.append(f"Price below floor for {match.get('name')}.")

    status = "valid" if not blockers else "blocked"
    return {
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "checked_at": utc_now().isoformat(),
    }


def _proposal_sections(lead: Lead, proposal: ProposalRequest, quote: Quote | None) -> dict[str, Any]:
    spec = proposal.spec_json or {}
    solution = proposal.solution_json or {}
    return {
        "executive_summary": (
            f"Proposal for {lead.name}: {spec.get('buyer_problem') or spec.get('required_products') or 'requested solution'}."
        ),
        "requirement_summary": spec,
        "recommended_solution": solution.get("recommended_items") or [],
        "assumptions": solution.get("assumptions") or [],
        "commercials": {
            "quote_id": quote.id if quote else proposal.quote_id,
            "quote_number": quote.quote_number if quote else None,
            "currency": quote.currency if quote else None,
            "total_amount": _decimal_str(quote.total_amount) if quote else None,
            "valid_until": quote.valid_until.isoformat() if quote and quote.valid_until else None,
        },
        "next_steps": [
            "Review the technical and commercial assumptions.",
            "Confirm missing requirement fields before final submission.",
            "Approve the proposal for dispatch.",
        ],
    }


def create_proposal_draft(
    session: Session,
    company_id: int,
    actor_user_id: int,
    *,
    lead_id: int,
    interaction_id: int | None = None,
    request_text: str | None = None,
    source_channel: str | None = None,
    auto_create_quote: bool = True,
) -> dict[str, Any]:
    lead = session.exec(select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    text = request_text or _latest_interaction_text(session, company_id, lead_id, interaction_id) or ""
    intent, confidence = _extract_intent(text)
    requirement = get_latest_requirements(session, company_id, lead_id)
    if not requirement and text:
        requirement = upsert_lead_requirements(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            data=LeadRequirementUpsert(
                lead_id=lead_id,
                interaction_id=interaction_id,
                use_case=text[:500],
                required_products=", ".join(q["item"] for q in _extract_quantity_items(text)) or None,
                structured_data={
                    "intent": intent,
                    "intent_confidence": float(confidence),
                    "quantities": _extract_quantity_items(text),
                    "next_action": "send_quote",
                },
            ),
        )

    spec = _requirement_to_spec(requirement, text, intent, confidence)
    solution = _build_solution(session, company_id, spec)
    quote: Quote | None = None
    if auto_create_quote:
        items = _quote_items_from_solution(solution)
        if items:
            quote = create_quote_for_solution(session, company_id, actor_user_id, lead, items)

    validation = _validate_solution_and_quote(session, company_id, spec, solution, quote)
    from services.tabular.proposal_predictor import score_proposal
    scores = score_proposal(
        session=session,
        company_id=company_id,
        lead=lead,
        quote=quote,
        spec=spec,
        solution=solution,
    )

    proposal = ProposalRequest(
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        requirement_id=requirement.id if requirement else None,
        quote_id=quote.id if quote else None,
        status="validated" if validation["status"] == "valid" else "needs_review",
        intent_type=intent,
        intent_confidence=confidence,
        source_channel=source_channel,
        request_text=text[:4000] if text else None,
        spec_json=spec,
        solution_json=solution,
        pricing_json={"quote_id": quote.id if quote else None, "auto_created": bool(quote)},
        validation_json=validation,
        tabular_scores_json=scores,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)

    document = create_proposal_document(session, company_id, actor_user_id, proposal.id)
    try:
        from services.proposal.proposal_pdf_service import generate_proposal_pdf
        document = generate_proposal_pdf(session, company_id, actor_user_id, proposal.id, document.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[proposal] PDF generation failed for proposal=%s: %s", proposal.id, exc)
    return serialize_proposal(session, proposal, document)


def create_quote_for_solution(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead: Lead,
    items: list[QuoteItemCreate],
) -> Quote:
    from services.quote.quote_service import create_quote

    quote = create_quote(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        data=QuoteCreate(
            lead_id=lead.id,
            account_id=lead.account_id,
            currency=items[0].unit_price and "INR" or "INR",
            valid_until=utc_now() + timedelta(days=15),
            notes="Auto-created from proposal/RFP workflow",
            items=items,
        ),
    )
    return quote


def get_proposal_or_404(session: Session, company_id: int, proposal_id: int) -> ProposalRequest:
    proposal = session.exec(
        select(ProposalRequest).where(ProposalRequest.id == proposal_id, ProposalRequest.company_id == company_id)
    ).first()
    if not proposal:
        raise HTTPException(status_code=404, detail="Proposal request not found")
    return proposal


def create_proposal_document(
    session: Session,
    company_id: int,
    actor_user_id: int,
    proposal_id: int,
) -> ProposalDocument:
    proposal = get_proposal_or_404(session, company_id, proposal_id)
    lead = session.get(Lead, proposal.lead_id)
    if not lead or lead.company_id != company_id:
        raise HTTPException(status_code=404, detail="Lead not found")
    quote = session.get(Quote, proposal.quote_id) if proposal.quote_id else None
    if quote and quote.company_id != company_id:
        quote = None

    current = session.exec(
        select(ProposalDocument)
        .where(ProposalDocument.company_id == company_id, ProposalDocument.proposal_request_id == proposal_id)
        .order_by(ProposalDocument.version.desc())
        .limit(1)
    ).first()
    version = (current.version + 1) if current else 1
    doc = ProposalDocument(
        company_id=company_id,
        proposal_request_id=proposal_id,
        quote_id=proposal.quote_id,
        version=version,
        status="draft",
        title=f"Proposal for {lead.name}",
        sections_json=_proposal_sections(lead, proposal, quote),
        validation_json=proposal.validation_json or {},
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(doc)
    session.commit()
    session.refresh(doc)
    return doc


def latest_document(session: Session, company_id: int, proposal_id: int) -> ProposalDocument | None:
    return session.exec(
        select(ProposalDocument)
        .where(ProposalDocument.company_id == company_id, ProposalDocument.proposal_request_id == proposal_id)
        .order_by(ProposalDocument.version.desc())
        .limit(1)
    ).first()


def enqueue_proposal_send(
    session: Session,
    company_id: int,
    actor_user_id: int,
    proposal_id: int,
    channels: list[str],
    subject: str | None = None,
    message: str | None = None,
    requires_approval: bool | None = None,
):
    from services.agent.agent_task_service import create_agent_task

    proposal = get_proposal_or_404(session, company_id, proposal_id)
    if (proposal.validation_json or {}).get("status") == "blocked":
        raise HTTPException(status_code=400, detail={"message": "Proposal is blocked by validation", "validation": proposal.validation_json})
    document = latest_document(session, company_id, proposal_id) or create_proposal_document(
        session, company_id, actor_user_id, proposal_id
    )
    if not document.pdf_path:
        try:
            from services.proposal.proposal_pdf_service import generate_proposal_pdf
            document = generate_proposal_pdf(session, company_id, actor_user_id, proposal_id, document.id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[proposal] PDF generation failed before send proposal=%s: %s", proposal_id, exc)
    raw = f"send_proposal|{company_id}|{proposal.lead_id}|{proposal_id}|{document.id}|{','.join(channels)}"
    key = f"send_proposal:{proposal.lead_id}:{hashlib.sha256(raw.encode()).hexdigest()[:32]}"
    return create_agent_task(
        session=session,
        company_id=company_id,
        lead_id=proposal.lead_id,
        task_type="send_proposal",
        assigned_agent="send",
        input_json={
            "task_type": "send_proposal",
            "proposal_id": proposal.id,
            "proposal_document_id": document.id,
            "quote_id": proposal.quote_id,
            "channels": channels,
            "subject": subject or f"Proposal for your requirement",
            "message": message or "Please review the attached proposal and quotation.",
            "summary": f"Send proposal #{proposal.id} to lead {proposal.lead_id} via {','.join(channels)}",
        },
        idempotency_key=key,
        requires_approval=requires_approval,
        actor_user_id=actor_user_id,
    )


def mark_proposal_sent(session: Session, company_id: int, proposal_id: int, document_id: int | None, actor_user_id: int) -> None:
    now = utc_now()
    proposal = get_proposal_or_404(session, company_id, proposal_id)
    proposal.status = "sent"
    proposal.updated_at = now
    proposal.updated_by = actor_user_id
    session.add(proposal)
    if document_id:
        doc = session.get(ProposalDocument, document_id)
        if doc and doc.company_id == company_id:
            doc.status = "sent"
            doc.sent_at = now
            doc.updated_at = now
            doc.updated_by = actor_user_id
            session.add(doc)
    session.commit()


def serialize_proposal(session: Session, proposal: ProposalRequest, document: ProposalDocument | None = None) -> dict[str, Any]:
    if document is None:
        document = latest_document(session, proposal.company_id, proposal.id)
    quote = session.get(Quote, proposal.quote_id) if proposal.quote_id else None
    return {
        "id": proposal.id,
        "lead_id": proposal.lead_id,
        "interaction_id": proposal.interaction_id,
        "requirement_id": proposal.requirement_id,
        "quote_id": proposal.quote_id,
        "quote_number": quote.quote_number if quote else None,
        "status": proposal.status,
        "intent_type": proposal.intent_type,
        "intent_confidence": float(proposal.intent_confidence),
        "source_channel": proposal.source_channel,
        "spec": proposal.spec_json,
        "solution": proposal.solution_json,
        "pricing": proposal.pricing_json,
        "validation": proposal.validation_json,
        "tabular_scores": proposal.tabular_scores_json,
        "document": {
            "id": document.id,
            "version": document.version,
            "status": document.status,
            "title": document.title,
            "sections": document.sections_json,
            "validation": document.validation_json,
            "pdf_path": document.pdf_path,
            "sent_at": document.sent_at.isoformat() if document.sent_at else None,
        } if document else None,
        "created_at": proposal.created_at.isoformat(),
        "updated_at": proposal.updated_at.isoformat(),
    }


def list_proposals(session: Session, company_id: int, lead_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    query = select(ProposalRequest).where(ProposalRequest.company_id == company_id)
    if lead_id is not None:
        query = query.where(ProposalRequest.lead_id == lead_id)
    rows = session.exec(query.order_by(ProposalRequest.created_at.desc()).limit(limit)).all()
    return [serialize_proposal(session, row) for row in rows]

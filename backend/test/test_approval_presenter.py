"""Tests for the approval payload presenter (Week 3.2).

Four invariants:
  1. Known task types return a presenter-shaped dict (title + description +
     preview + warnings + raw)
  2. Unknown task types fall through to a generic presenter — never raise
  3. Lead / Quote lookups gracefully degrade when session is None OR when
     the referenced row doesn't exist
  4. Heuristic warnings fire on flagged payloads (multi-channel quote,
     overlong WhatsApp)
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.models import Lead, Quote
from services.agent.approval_presenter import present


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


# Shape — every presenter must return the same keys

class TestPresenterShape:
    @pytest.mark.parametrize("task_type,payload", [
        ("send_email", {"subject": "Hi", "body": "Hello"}),
        ("send_whatsapp", {"body": "Quick check"}),
        ("send_quote", {"quote_id": 1, "channels": ["email"], "subject": "q"}),
    ])
    def test_known_task_returns_full_shape(self, task_type, payload):
        result = present(task_type, payload, company_id=1)
        assert "title" in result
        assert "description" in result
        assert "preview" in result
        assert "warnings" in result
        assert "raw" in result
        assert isinstance(result["warnings"], list)

    def test_unknown_task_falls_back_gracefully(self):
        result = present(
            "invoice_sync_hubspot",
            {"summary": "Push lead 42 to HubSpot"},
            company_id=1,
        )
        assert "invoice_sync_hubspot" in result["title"]
        assert result["preview"] is None       # no per-type renderer
        assert result["warnings"] == []
        assert result["description"]           # uses the `summary` field

    def test_raw_excludes_internal_bookkeeping_fields(self):
        """The UI's 'raw' payload view shouldn't leak task_type/summary noise."""
        result = present(
            "send_email",
            {"subject": "Hi", "body": "x", "task_type": "send_email", "summary": "Send email to X"},
            company_id=1,
        )
        assert "task_type" not in result["raw"]
        assert "summary" not in result["raw"]
        assert "subject" in result["raw"]


# Lead name resolution

class TestLeadResolution:
    def test_lead_name_resolved_when_lead_exists(self, session):
        lead = Lead(company_id=1, name="Jane Doe", normalized_phone="+111", email="j@d.com")
        session.add(lead); session.commit(); session.refresh(lead)

        result = present(
            "send_email",
            {"subject": "Hi", "body": "x"},
            company_id=1, lead_id=lead.id, session=session,
        )
        assert "Jane Doe" in result["title"]
        assert f"lead #{lead.id}" in result["title"]

    def test_missing_lead_uses_id_only(self, session):
        result = present(
            "send_email",
            {"subject": "Hi", "body": "x"},
            company_id=1, lead_id=999, session=session,
        )
        assert "lead #999" in result["title"]

    def test_no_session_uses_id_only(self):
        """Without a session we can't look up lead name — degrade to ID format."""
        result = present(
            "send_email",
            {"subject": "Hi", "body": "x"},
            company_id=1, lead_id=42,
        )
        assert "lead #42" in result["title"]

    def test_null_lead_id_returns_unknown(self):
        result = present(
            "send_email",
            {"subject": "Hi", "body": "x"},
            company_id=1, lead_id=None,
        )
        assert "unknown lead" in result["title"]


# send_email presenter specifics

class TestSendEmailPresenter:
    def test_preview_includes_subject_and_body(self):
        result = present(
            "send_email",
            {"subject": "Welcome", "body": "Glad you're here.", "cta_url": "https://rio.app/start", "cta_label": "Get Started"},
            company_id=1, lead_id=42,
        )
        preview = result["preview"]
        assert preview["subject"] == "Welcome"
        assert preview["body"] == "Glad you're here."
        assert preview["cta"] == "Get Started → https://rio.app/start"
        assert preview["channel"] == "email"

    def test_no_cta_omits_cta_field(self):
        result = present(
            "send_email",
            {"subject": "Hi", "body": "x"},
            company_id=1, lead_id=42,
        )
        assert result["preview"]["cta"] is None

    def test_long_body_is_truncated_in_preview(self):
        result = present(
            "send_email",
            {"subject": "s", "body": "word " * 500},  # 2500+ chars
            company_id=1, lead_id=42,
        )
        assert len(result["preview"]["body"]) <= 801  # 800 + ellipsis

    def test_missing_subject_labeled_no_subject(self):
        result = present(
            "send_email",
            {"body": "x"},
            company_id=1, lead_id=42,
        )
        assert "(no subject)" in result["description"]


# send_whatsapp presenter — warning for overlong messages

class TestSendWhatsappPresenter:
    def test_short_message_no_warning(self):
        result = present(
            "send_whatsapp",
            {"body": "Hi, quick check — are you free tomorrow at 3?"},
            company_id=1, lead_id=42,
        )
        assert result["warnings"] == []

    def test_overlong_message_triggers_truncation_warning(self):
        result = present(
            "send_whatsapp",
            {"body": "x" * 1500},  # > 1,000 char threshold
            company_id=1, lead_id=42,
        )
        assert any("truncate" in w.lower() for w in result["warnings"])

    def test_empty_body_labeled_empty_message(self):
        result = present(
            "send_whatsapp",
            {"body": ""},
            company_id=1, lead_id=42,
        )
        assert "(empty message)" in result["description"]


# send_quote presenter — warning for multi-channel

class TestSendQuotePresenter:
    def test_quote_summary_resolved_when_quote_exists(self, session):
        lead = Lead(company_id=1, name="x", normalized_phone="+1", email="a@b.c")
        session.add(lead); session.commit(); session.refresh(lead)
        quote = Quote(
            company_id=1, lead_id=lead.id, quote_number="Q-2026-042",
            currency="USD", total_amount=Decimal("12500.00"),
        )
        session.add(quote); session.commit(); session.refresh(quote)

        result = present(
            "send_quote",
            {"quote_id": quote.id, "channels": ["email"]},
            company_id=1, lead_id=lead.id, session=session,
        )
        assert "Q-2026-042" in result["title"]
        assert "12,500.00" in result["title"]

    def test_multi_channel_triggers_warning(self, session):
        result = present(
            "send_quote",
            {"quote_id": 1, "channels": ["email", "whatsapp"]},
            company_id=1, lead_id=42, session=session,
        )
        assert any("channels" in w.lower() for w in result["warnings"])

    def test_single_channel_no_warning(self):
        result = present(
            "send_quote",
            {"quote_id": 1, "channels": ["email"]},
            company_id=1, lead_id=42,
        )
        assert result["warnings"] == []

    def test_missing_quote_id_shows_unresolved(self):
        result = present(
            "send_quote",
            {"channels": ["email"]},
            company_id=1, lead_id=42,
        )
        # No quote_id in payload → presenter says "unresolved"
        assert "unresolved" in result["title"] or "quote" in result["title"].lower()


# Defensive: presenter never raises

class TestNeverRaises:
    @pytest.mark.parametrize("bad_payload", [
        {},
        {"subject": None, "body": None},
        {"body": 42},               # int instead of str
        {"channels": "email"},      # string instead of list
        {"quote_id": "not-a-number"},
    ])
    def test_malformed_payload_still_returns_result(self, bad_payload):
        for task_type in ("send_email", "send_whatsapp", "send_quote"):
            # Should not raise
            result = present(task_type, bad_payload, company_id=1, lead_id=42)
            assert "title" in result
            assert "raw" in result

"""Week 2.4 — End-to-end integration test.

Exercises the full pipe from a simulated webhook through the durable queue
into the send executor. Uses in-memory SQLite + stubbed communication_service,
so no network calls / no real Twilio or SMTP.

What this test proves:
  1. A webhook audit creates a durable AgentTask
  2. ISM dispatch (enqueue_send_email) creates a separate AgentTask
  3. Idempotency holds across the full pipe (double webhook → one audit task)
  4. The send executor, when invoked via run_agent, dispatches to the right
     underlying service function

It does NOT test the actual HTTP routes or the worker's long-running loop —
those live behind FastAPI app + real db. Next week's integration will add
that layer once the executor contracts are stable.
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import sys
import types

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models.models import AgentTask, Lead, LeadRequirement


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


@pytest.fixture(autouse=True)
def _queue_on(monkeypatch):
    monkeypatch.setenv("USE_AGENT_TASK_QUEUE", "1")


def _seed_lead(session: Session, **overrides) -> Lead:
    defaults = {
        "company_id": 1,
        "name": "Test Lead",
        "normalized_phone": "+919876543210",
        "email": "lead@example.com",
        "ism_stage": "engaged",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


class TestE2EIsmFlow:
    """Simulated lifecycle: webhook arrives → audit enqueued → ISM runs →
    send task enqueued → worker claims send task → executor runs.
    """

    def test_webhook_audit_and_ism_send_create_distinct_tasks(self, session):
        """Two independent triggers (webhook event + ISM dispatch) each create
        their own durable AgentTask row. Audit dedupes on replay; send dedupes
        on same (lead, trigger, content)."""
        from services.agent.dispatch_service import enqueue_send_email
        from services.agent.webhook_audit_service import enqueue_webhook_audit

        lead = _seed_lead(session)

        # Step 1: simulated incoming webhook
        audit = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_whatsapp_inbound",
            provider_event_id="SMabc123",
            payload={"Body": "interested", "From": lead.normalized_phone},
            lead_id=lead.id,
        )
        assert audit.task_type == "webhook_audit"

        # Step 2: ISM decides to send email (simulated)
        send_task = enqueue_send_email(
            session, company_id=1, lead_id=lead.id, actor_user_id=0,
            subject="Thanks for your reply",
            body="Next steps attached",
            trigger="ism_stage:engaged:attempt:0",
        )
        assert send_task.task_type == "send_email"
        assert send_task.assigned_agent == "send"
        assert send_task.requires_approval is True  # HITL gate for send_email

        # Both tasks exist, distinct rows
        all_tasks = session.exec(select(AgentTask)).all()
        assert len(all_tasks) == 2
        task_types = {t.task_type for t in all_tasks}
        assert task_types == {"webhook_audit", "send_email"}

    def test_webhook_retry_dedupes_but_send_retries_are_independent(self, session):
        """Twilio retries audit the SAME event → one audit row. But a second
        ISM dispatch AFTER a successful send (different attempt_count) is a
        legitimately new task."""
        from services.agent.dispatch_service import enqueue_send_email
        from services.agent.webhook_audit_service import enqueue_webhook_audit

        lead = _seed_lead(session)

        # Webhook fires twice (Twilio retry)
        enqueue_webhook_audit(
            session, company_id=1, event_type="twilio_whatsapp_inbound",
            provider_event_id="SM1", payload={}, lead_id=lead.id,
        )
        enqueue_webhook_audit(
            session, company_id=1, event_type="twilio_whatsapp_inbound",
            provider_event_id="SM1", payload={}, lead_id=lead.id,
        )

        audits = session.exec(
            select(AgentTask).where(AgentTask.task_type == "webhook_audit")
        ).all()
        assert len(audits) == 1, "Webhook retry must dedupe"

        # ISM dispatches email first attempt, then second attempt
        enqueue_send_email(
            session, company_id=1, lead_id=lead.id, actor_user_id=0,
            subject="Hi", body="x", trigger="ism_stage:engaged:attempt:0",
        )
        enqueue_send_email(
            session, company_id=1, lead_id=lead.id, actor_user_id=0,
            subject="Hi", body="x", trigger="ism_stage:engaged:attempt:1",
        )

        sends = session.exec(
            select(AgentTask).where(AgentTask.task_type == "send_email")
        ).all()
        assert len(sends) == 2, "Different attempt triggers → different tasks"

    @pytest.mark.asyncio
    async def test_send_executor_dispatches_to_communication_service(self, monkeypatch):
        """The send agent's run() function routes to the right underlying
        sender based on task_type — this pins the contract between executor
        and communication_service."""
        calls = []

        def stub_send_email(**kwargs):
            calls.append(("email", kwargs))
            return {"sent": True, "to": kwargs.get("lead_id")}

        def stub_send_whatsapp(**kwargs):
            calls.append(("whatsapp", kwargs))
            return {"sent": True}

        stub_mod = types.ModuleType("services.communication.communication_service")
        stub_mod.send_email_to_lead = stub_send_email
        stub_mod.send_whatsapp_to_lead = stub_send_whatsapp
        # ism_orchestrator is transitively loaded by agents/__init__ — keep
        # its top-level import happy. Dummy attrs are fine; tests don't invoke
        # ism paths, so the noops are never called.
        stub_mod.get_company_setting_value = lambda *a, **kw: None
        stub_mod.send_quote_to_lead = lambda *a, **kw: {}
        monkeypatch.setitem(
            sys.modules, "services.communication.communication_service", stub_mod
        )

        from agents.send import run

        email_result = await run(
            company_id=1, actor_user_id=0, lead_id=42,
            task_type="send_email",
            subject="Welcome", body="Hello there",
        )
        assert email_result["ok"] is True
        assert email_result["channel"] == "email"
        assert len(calls) == 1
        assert calls[0][0] == "email"
        assert calls[0][1]["subject"] == "Welcome"
        assert calls[0][1]["lead_id"] == 42

        whatsapp_result = await run(
            company_id=1, actor_user_id=0, lead_id=42,
            task_type="send_whatsapp",
            body="quick check",
        )
        assert whatsapp_result["ok"] is True
        assert whatsapp_result["channel"] == "whatsapp"
        assert len(calls) == 2
        assert calls[1][0] == "whatsapp"

    def test_requirement_driven_channel_plus_send_enqueue(self, session, monkeypatch):
        """Full-flow taste: a lead with high budget triggers call-preference;
        ISM sees no phone → falls to email → enqueues send_email."""
        from agents.ism_orchestrator import _pick_channel
        from services.agent.dispatch_service import enqueue_send_email

        lead = _seed_lead(
            session,
            normalized_phone="",   # no phone → can't call/whatsapp
            email="ceo@bigco.com",
        )
        req = LeadRequirement(
            company_id=1, lead_id=lead.id, budget_range="$50k", timeline="",
        )
        session.add(req); session.commit()

        # Requirement says "high-ticket → prefer call", but lead has no phone
        # → guards knock out call + whatsapp → email wins
        channel = _pick_channel(session, 1, lead, stage="engaged")
        assert channel == "email"

        # ISM would then enqueue
        task = enqueue_send_email(
            session, company_id=1, lead_id=lead.id, actor_user_id=0,
            subject="Ready for a demo?", body="We'd love to show you.",
            trigger="ism_stage:engaged:attempt:0",
        )
        assert task.status in ("pending", "awaiting_approval")
        assert task.task_type == "send_email"

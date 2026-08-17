from datetime import datetime, timezone
from types import SimpleNamespace

from mcp_tools.executors.crm import _serialize_lead_context
from mcp_tools.registration import populate
from mcp_tools.registry import ToolRegistry


def test_crm_registry_exposes_get_lead_context() -> None:
    registry = ToolRegistry()
    populate(registry)

    assert "get_lead_context" in registry.list_all()


def test_serialize_lead_context_includes_timezone_and_appointments() -> None:
    lead = SimpleNamespace(
        id=1,
        name="Lokesh Kumar",
        normalized_phone="+919999999999",
        email="lokesh@example.com",
        status="qualified",
        ism_stage="scheduled",
        company_name="Example Co",
        job_title=None,
        owner_user_id=7,
        product_interest="TV for Ads",
        budget_range=None,
        timeline=None,
        next_action="Demo",
        next_action_due_at=None,
        lead_score=None,
        source="voice",
        timezone="Asia/Kolkata",
        preferred_language="en",
    )
    interaction = SimpleNamespace(
        id=10,
        type="call",
        channel="voice",
        direction="inbound",
        status="completed",
        content="Tomorrow at 10 AM works.",
        created_at=datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
        started_at=datetime(2026, 8, 13, 10, 0, tzinfo=timezone.utc),
    )
    requirement = SimpleNamespace(
        id=3,
        use_case="Advertising display",
        budget_range=None,
        timeline="tomorrow",
        decision_maker=None,
        pain_points=None,
        required_products="TV for Ads",
        notes=None,
        structured_data={"demo_type": "online"},
    )
    appointment = SimpleNamespace(
        id=5,
        appointment_time=datetime(2026, 8, 14, 4, 30, tzinfo=timezone.utc),
        status="scheduled",
        notes="Canonical appointment",
        meeting_link="https://meet.example/demo",
        calendar_event_id="evt_123",
        created_at=datetime(2026, 8, 13, 10, 1, tzinfo=timezone.utc),
    )

    payload = _serialize_lead_context(
        lead,
        effective_timezone="Asia/Kolkata",
        interactions=[interaction],
        requirement=requirement,
        appointments=[appointment],
    )

    assert payload["effective_timezone"] == "Asia/Kolkata"
    assert payload["timezone_source"] == "lead.timezone"
    assert payload["appointments"][0]["calendar_event_id"] == "evt_123"
    assert payload["recent_interactions"][0]["content"] == "Tomorrow at 10 AM works."

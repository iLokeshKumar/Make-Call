"""Unit tests for ICP scoring logic (compute_icp_score).

Tests exercise the pure scoring function directly — no DB, no network.
"""
from decimal import Decimal

from services.leads.demand_generation_service import compute_icp_score


# Profile completeness (max 60 pts)

def test_bare_lead_scores_zero(bare_lead):
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("0.00")
    assert result["priority"] == "low"
    assert result["reasons"] == []


def test_email_adds_20(bare_lead):
    bare_lead.email = "user@example.com"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("20.00")
    assert "lead_has_email" in result["reasons"]


def test_website_adds_15(bare_lead):
    bare_lead.website = "https://example.com"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("15.00")
    assert "lead_has_website" in result["reasons"]


def test_target_industry_adds_25(bare_lead):
    for industry in ("tech", "saas", "manufacturing", "healthcare", "finance"):
        bare_lead.industry = industry
        result = compute_icp_score(bare_lead)
        assert result["score"] == Decimal("25.00"), f"Failed for industry={industry}"
        assert "target_industry_match" in result["reasons"]


def test_non_target_industry_adds_nothing(bare_lead):
    bare_lead.industry = "hospitality"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("0.00")


def test_decision_maker_seniority_adds_15(bare_lead):
    for title in ("CEO", "VP Sales", "Head of Engineering", "Director", "Founder"):
        bare_lead.job_title = title
        result = compute_icp_score(bare_lead)
        assert result["score"] == Decimal("15.00"), f"Failed for title={title}"
        assert "decision_maker_seniority" in result["reasons"]


def test_high_intent_source_adds_10(bare_lead):
    bare_lead.source = "apollo"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("10.00")
    assert "high_intent_source" in result["reasons"]


def test_enriched_status_adds_15(bare_lead):
    bare_lead.enrichment_status = "fully_enriched"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("15.00")
    assert "already_enriched" in result["reasons"]


# Interaction history (max 20 pts)

def test_call_interaction_adds_8(bare_lead):
    result = compute_icp_score(bare_lead, interaction_counts={"call": 1})
    assert result["score"] == Decimal("8.00")
    assert "prior_call_contact" in result["reasons"]


def test_whatsapp_interaction_adds_6(bare_lead):
    result = compute_icp_score(bare_lead, interaction_counts={"whatsapp": 2})
    assert result["score"] == Decimal("6.00")


def test_email_interaction_adds_6(bare_lead):
    result = compute_icp_score(bare_lead, interaction_counts={"email": 1})
    assert result["score"] == Decimal("6.00")


def test_all_interactions_add_20(bare_lead):
    result = compute_icp_score(
        bare_lead,
        interaction_counts={"call": 1, "whatsapp": 1, "email": 1},
    )
    assert result["score"] == Decimal("20.00")


# Engagement signals (max 20 pts)

def test_reply_adds_10(bare_lead):
    result = compute_icp_score(bare_lead, engagement_counts={"reply": 1})
    assert result["score"] == Decimal("10.00")
    assert "lead_replied" in result["reasons"]


def test_whatsapp_reply_also_counts(bare_lead):
    result = compute_icp_score(bare_lead, engagement_counts={"whatsapp_reply": 1})
    assert result["score"] == Decimal("10.00")
    assert "lead_replied" in result["reasons"]


def test_click_adds_6(bare_lead):
    result = compute_icp_score(bare_lead, engagement_counts={"click": 1})
    assert result["score"] == Decimal("6.00")
    assert "link_clicked" in result["reasons"]


def test_open_needs_at_least_2(bare_lead):
    result1 = compute_icp_score(bare_lead, engagement_counts={"open": 1})
    assert result1["score"] == Decimal("0.00")

    result2 = compute_icp_score(bare_lead, engagement_counts={"open": 2})
    assert result2["score"] == Decimal("4.00")
    assert "email_opened_multiple_times" in result2["reasons"]


def test_all_engagement_adds_20(bare_lead):
    result = compute_icp_score(
        bare_lead,
        engagement_counts={"reply": 1, "click": 1, "open": 3},
    )
    assert result["score"] == Decimal("20.00")


# Score capping and priority thresholds

def test_max_score_capped_at_100(enriched_lead):
    """Enriched lead (100 profile pts uncapped) + all interactions + all engagement."""
    result = compute_icp_score(
        enriched_lead,
        interaction_counts={"call": 1, "whatsapp": 1, "email": 1},
        engagement_counts={"reply": 1, "click": 1, "open": 5},
    )
    assert result["score"] == Decimal("100.00")
    assert result["priority"] == "high"


def test_priority_high_at_70(bare_lead):
    # email(20) + website(15) + industry(25) + seniority(15) = 75
    bare_lead.email = "a@b.com"
    bare_lead.website = "https://b.com"
    bare_lead.industry = "tech"
    bare_lead.job_title = "CEO"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("75.00")
    assert result["priority"] == "high"


def test_priority_medium_at_40(bare_lead):
    # email(20) + industry(25) = 45
    bare_lead.email = "a@b.com"
    bare_lead.industry = "saas"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("45.00")
    assert result["priority"] == "medium"


def test_priority_low_under_40(bare_lead):
    # email(20) + website(15) = 35
    bare_lead.email = "a@b.com"
    bare_lead.website = "https://example.com"
    result = compute_icp_score(bare_lead)
    assert result["score"] == Decimal("35.00")
    assert result["priority"] == "low"


# Edge cases

def test_none_interaction_and_engagement_counts(bare_lead):
    result = compute_icp_score(bare_lead, None, None)
    assert result["score"] == Decimal("0.00")


def test_industry_case_insensitive(bare_lead):
    bare_lead.industry = "TECH"
    result = compute_icp_score(bare_lead)
    assert "target_industry_match" in result["reasons"]


def test_job_title_case_insensitive(bare_lead):
    bare_lead.job_title = "DIRECTOR of Sales"
    # "director" keyword is matched case-insensitively
    result = compute_icp_score(bare_lead)
    assert "decision_maker_seniority" in result["reasons"]

"""Agents package — multi-agent Rio CRM system."""

from .ism_orchestrator import run_ism_cycle, run_ism_for_company

# Phase 3: agent node functions + tool lists
from .knowledge import knowledge_node, KNOWLEDGE_TOOLS, create_agent as create_knowledge_agent
from .enrichment import enrichment_node, ENRICHMENT_TOOLS, create_agent as create_enrichment_agent
from .researcher import researcher_node, RESEARCHER_TOOLS, create_agent as create_researcher_agent
from .post_call import post_call_node, POST_CALL_TOOLS, create_agent as create_post_call_agent
from .coach import coach_node, COACH_TOOLS, create_agent as create_coach_agent
from .ism import ism_node, ISM_TOOLS, create_agent as create_ism_agent
from .campaign import campaign_node, CAMPAIGN_TOOLS, create_agent as create_campaign_agent
from .quote import quote_node, QUOTE_TOOLS, create_agent as create_quote_agent
from .analytics import analytics_node, ANALYTICS_TOOLS, create_agent as create_analytics_agent

# Master orchestrator entry points
from .orchestrator import run_pre_call, run_post_call, run_agent, ask

__all__ = [
    # ISM orchestrator (legacy)
    "run_ism_cycle",
    "run_ism_for_company",
    # Node functions
    "knowledge_node",
    "enrichment_node",
    "researcher_node",
    "post_call_node",
    "coach_node",
    "ism_node",
    "campaign_node",
    "quote_node",
    "analytics_node",
    # create_react_agent factories
    "create_knowledge_agent",
    "create_enrichment_agent",
    "create_researcher_agent",
    "create_post_call_agent",
    "create_coach_agent",
    "create_ism_agent",
    "create_campaign_agent",
    "create_quote_agent",
    "create_analytics_agent",
    # Tool lists
    "KNOWLEDGE_TOOLS",
    "ENRICHMENT_TOOLS",
    "RESEARCHER_TOOLS",
    "POST_CALL_TOOLS",
    "COACH_TOOLS",
    "ISM_TOOLS",
    "CAMPAIGN_TOOLS",
    "QUOTE_TOOLS",
    "ANALYTICS_TOOLS",
    # Master orchestrator
    "run_pre_call",
    "run_post_call",
    "run_agent",
    "ask",
]

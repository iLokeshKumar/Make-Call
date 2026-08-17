"""Agents package — multi-agent Rio CRM system."""

from .ism_orchestrator import run_ism_cycle, run_ism_for_company

# create_react_agent factories + tool lists (LangGraph ReAct agents)
from .knowledge import KNOWLEDGE_TOOLS, create_agent as create_knowledge_agent
from .enrichment import ENRICHMENT_TOOLS, create_agent as create_enrichment_agent
from .researcher import RESEARCHER_TOOLS, create_agent as create_researcher_agent
from .post_call import POST_CALL_TOOLS, create_agent as create_post_call_agent
from .coach import COACH_TOOLS, create_agent as create_coach_agent
from .ism import ISM_TOOLS, create_agent as create_ism_agent
from .campaign import CAMPAIGN_TOOLS, create_agent as create_campaign_agent
from .quote import QUOTE_TOOLS, create_agent as create_quote_agent
from .proposal import PROPOSAL_TOOLS, create_agent as create_proposal_agent
from .analytics import ANALYTICS_TOOLS, create_agent as create_analytics_agent

# Master orchestrator entry points
from .orchestrator import run_pre_call, run_post_call, run_agent, ask

__all__ = [
    # ISM orchestrator (legacy)
    "run_ism_cycle",
    "run_ism_for_company",
    # create_react_agent factories
    "create_knowledge_agent",
    "create_enrichment_agent",
    "create_researcher_agent",
    "create_post_call_agent",
    "create_coach_agent",
    "create_ism_agent",
    "create_campaign_agent",
    "create_quote_agent",
    "create_proposal_agent",
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
    "PROPOSAL_TOOLS",
    "ANALYTICS_TOOLS",
    # Master orchestrator
    "run_pre_call",
    "run_post_call",
    "run_agent",
    "ask",
]

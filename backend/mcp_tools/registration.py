"""
Wire all tools into the ToolRegistry.

Call populate(registry) once at server startup (e.g. from AsyncMCPServer.__init__).
"""
from __future__ import annotations

from mcp_tools.registry import RegisteredTool, ToolRegistry
from mcp_tools.specs import (
    analytics,
    apollo,
    capabilities,
    contacts,
    crm,
    enrichment,
    inventory,
    knowledge,
    post_call,
    schedule,
    zoho,
)


def populate(registry: ToolRegistry) -> None:
    _knowledge(registry)
    _inventory(registry)
    _analytics(registry)
    _crm(registry)
    _schedule(registry)
    _zoho(registry)
    _apollo(registry)
    _post_call(registry)
    _enrichment(registry)
    _contacts(registry)
    _capabilities(registry)


def _knowledge(registry: ToolRegistry) -> None:
    for spec, attr in [
        (knowledge.search_knowledge_base, "search_knowledge_base"),
        (knowledge.get_objection_rebuttal, "get_objection_rebuttal"),
        (knowledge.get_competitor_intel, "get_competitor_intel"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.knowledge",
            attr_name=attr,
            spec=spec,
            category="knowledge",
        ))


def _inventory(registry: ToolRegistry) -> None:
    for spec, attr in [
        (inventory.get_product_info, "get_product_info"),
        (inventory.create_quote_for_lead, "create_quote_for_lead"),
        (inventory.sync_product_catalog, "sync_product_catalog"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.inventory",
            attr_name=attr,
            spec=spec,
            category="inventory",
        ))


def _analytics(registry: ToolRegistry) -> None:
    for spec, attr in [
        (analytics.get_pipeline_funnel, "get_pipeline_funnel"),
        (analytics.get_engagement_summary, "get_engagement_summary"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.analytics",
            attr_name=attr,
            spec=spec,
            category="analytics",
        ))


def _crm(registry: ToolRegistry) -> None:
    for spec, attr in [
        (crm.get_or_create_lead, "get_or_create_lead"),
        (crm.get_lead_info, "get_lead_info"),
        (crm.update_lead_status, "update_lead_status"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.crm",
            attr_name=attr,
            spec=spec,
            category="crm",
        ))


def _zoho(registry: ToolRegistry) -> None:
    for spec, attr in [
        (zoho.zoho_get_pipeline, "zoho_get_pipeline"),
        (zoho.zoho_create_deal, "zoho_create_deal"),
        (zoho.zoho_update_contact, "zoho_update_contact"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.zoho",
            attr_name=attr,
            spec=spec,
            category="zoho",
        ))


def _apollo(registry: ToolRegistry) -> None:
    for spec, attr in [
        (apollo.apollo_search_leads, "apollo_search_leads"),
        (apollo.apollo_enrich_contact, "apollo_enrich_contact"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.apollo",
            attr_name=attr,
            spec=spec,
            category="apollo",
        ))


def _post_call(registry: ToolRegistry) -> None:
    for spec, attr in [
        (post_call.get_lead_requirements, "get_lead_requirements"),
        (post_call.upsert_lead_requirements, "upsert_lead_requirements"),
        (post_call.send_csat, "send_csat"),
        (post_call.create_ticket, "create_ticket"),
        (post_call.list_tickets, "list_tickets"),
        (post_call.set_next_action, "set_next_action"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.post_call",
            attr_name=attr,
            spec=spec,
            category="post_call",
        ))


def _enrichment(registry: ToolRegistry) -> None:
    for spec, attr in [
        (enrichment.score_lead, "score_lead"),
        (enrichment.recommend_channel, "recommend_channel"),
        (enrichment.check_opt_out, "check_opt_out"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.enrichment",
            attr_name=attr,
            spec=spec,
            category="enrichment",
        ))


def _contacts(registry: ToolRegistry) -> None:
    for spec, attr in [
        (contacts.create_contact, "create_contact"),
        (contacts.list_contacts, "list_contacts"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.contacts",
            attr_name=attr,
            spec=spec,
            category="contacts",
        ))


def _schedule(registry: ToolRegistry) -> None:
    for spec, attr in [
        (schedule.book_meeting, "book_meeting"),
        (schedule.book_demo, "book_demo"),
        (schedule.get_google_auth_url, "get_google_auth_url"),
        (schedule.submit_google_auth_code, "submit_google_auth_code"),
    ]:
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.schedule",
            attr_name=attr,
            spec=spec,
            category="schedule",
        ))


def _capabilities(registry: ToolRegistry) -> None:
    """Register connector-backed capability tools (Apollo/RocketReach, Zoho,
    Cal.com/Calendly, inventory). Each routes through the capability router at
    execution time, so connected apps are usable by dispatcher-based flows too."""
    for spec in capabilities.all_capability_specs():
        registry.register(RegisteredTool(
            name=spec.name,
            module_path="mcp_tools.executors.capabilities",
            attr_name=spec.name,
            spec=spec,
            category=spec.category,
        ))

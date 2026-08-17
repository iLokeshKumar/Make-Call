from dataclasses import dataclass

@dataclass
class RoutingDecision:
    category: str
    tools: list[str]
    reason: str

class ToolRouter:
    def __init__(self, registry):
        self.registry = registry

    def route(self, query: str) -> RoutingDecision:
        q = query.lower()

        if any(x in q for x in ["meeting", "schedule", "calendar", "demo"]):
            return RoutingDecision(
                category="schedule",
                tools=["book_meeting", "book_demo", "get_google_auth_url", "submit_google_auth_code"],
                reason="Scheduling intent detected",
            )
        if any(x in q for x in ["product", "price", "sku", "stock", "inventory", "quote"]):
            return RoutingDecision(
                category="inventory",
                tools=["get_product_info", "create_quote_for_lead", "sync_product_catalog"],
                reason="Inventory/catalog intent detected",
            )
        if any(x in q for x in ["knowledge", "objection", "competitor", "playbook"]):
            return RoutingDecision(
                category="knowledge",
                tools=["search_knowledge_base", "get_objection_rebuttal", "get_competitor_intel"],
                reason="Knowledge retrieval intent detected",
            )
        if any(x in q for x in ["pipeline", "funnel", "analytics", "engagement"]):
            return RoutingDecision(
                category="analytics",
                tools=["get_pipeline_funnel", "get_engagement_summary"],
                reason="Analytics intent detected",
            )
        if any(x in q for x in ["ticket", "complaint", "issue", "service request", "sla"]):
            return RoutingDecision(
                category="post_call",
                tools=["create_ticket", "list_tickets"],
                reason="Service/support intent detected",
            )
        if any(x in q for x in ["requirements", "budget", "timeline", "use case", "pain point"]):
            return RoutingDecision(
                category="post_call",
                tools=["get_lead_requirements", "upsert_lead_requirements"],
                reason="Requirements capture intent detected",
            )
        if any(x in q for x in ["csat", "survey", "satisfaction"]):
            return RoutingDecision(
                category="post_call",
                tools=["send_csat"],
                reason="CSAT intent detected",
            )
        if any(x in q for x in ["next action", "follow up", "follow-up", "call back"]):
            return RoutingDecision(
                category="post_call",
                tools=["set_next_action"],
                reason="Next action scheduling intent detected",
            )
        if any(x in q for x in ["score", "priority", "rank", "hot lead", "qualify"]):
            return RoutingDecision(
                category="enrichment",
                tools=["score_lead"],
                reason="Lead scoring intent detected",
            )
        if any(x in q for x in ["channel", "email or call", "reach out", "outreach method"]):
            return RoutingDecision(
                category="enrichment",
                tools=["recommend_channel"],
                reason="Channel recommendation intent detected",
            )
        if any(x in q for x in ["opt out", "opted out", "unsubscribed", "do not contact"]):
            return RoutingDecision(
                category="enrichment",
                tools=["check_opt_out"],
                reason="Opt-out check intent detected",
            )
        if any(x in q for x in ["contact", "stakeholder", "decision maker", "buying committee"]):
            return RoutingDecision(
                category="contacts",
                tools=["list_contacts", "create_contact"],
                reason="Contact management intent detected",
            )
        if any(x in q for x in ["zoho", "crm deal", "deal stage"]):
            return RoutingDecision(
                category="zoho",
                tools=["zoho_get_pipeline", "zoho_create_deal", "zoho_update_contact"],
                reason="Zoho CRM intent detected",
            )
        if any(x in q for x in ["apollo", "search leads", "enrich", "prospect"]):
            return RoutingDecision(
                category="apollo",
                tools=["apollo_search_leads", "apollo_enrich_contact"],
                reason="Apollo intent detected",
            )

        return RoutingDecision(
            category="general",
            tools=["ask_rio"],
            reason="Fallback to supervisor tool",
        )
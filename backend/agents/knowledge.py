"""
Knowledge Agent — searches the company KB and injects context into RioState.
"""
from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async
logger = logging.getLogger(__name__)

@tool
def search_knowledge_base(query: str, collection: str = "all", company_id: int = 0, n_results: int = 5) -> str:
    """Search the company knowledge base using hybrid RAG.

    Args:
        query: Natural-language search query.
        collection: One of 7 KB collections or "all" for cross-collection search.
        company_id: Tenant ID (required).
        n_results: Maximum chunks to return.
    """
    if not company_id:
        return "company_id is required to search the knowledge base."
    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = rag_search(query, company_id=company_id, collection=collection, n_results=n_results)
        return format_for_prompt(results)
    except Exception as exc:
        logger.warning("[KnowledgeAgent] search failed: %s", exc)
        return f"Knowledge base search unavailable: {exc}"


@tool
def list_kb_collections(company_id: int = 0) -> str:
    """Return names of all available KB collections.

    Args:
        company_id: Tenant ID (required).
    """
    if not company_id:
        return "company_id is required."
    try:
        from services.rag.collections import COLLECTION_NAMES
        return ", ".join(COLLECTION_NAMES)
    except Exception as exc:
        return f"Could not list collections: {exc}"


KNOWLEDGE_TOOLS = [search_knowledge_base, list_kb_collections]


@traceable(name="knowledge_node", run_type="chain", tags=['knowledge', 'rag'])
def knowledge_node(state: dict) -> dict:
    """LangGraph node: populate state[kb_context] with RAG results."""
    company_id = state.get("company_id", 0)
    lead_data = state.get("lead_data", {})
    industry = lead_data.get("industry") or lead_data.get("company_industry") or ""
    role = lead_data.get("title") or lead_data.get("job_title") or ""
    query = f"sales pitch {industry} {role}".strip() or "product overview value proposition"
    results: list[str] = []
    for collection in ("products", "objections", "competitors"):
        text = search_knowledge_base.invoke({"query": query, "collection": collection, "company_id": company_id, "n_results": 3})
        if text and "unavailable" not in text.lower():
            results.append(f"[{collection.upper()}]\n{text}")
    state["kb_context"] = results
    return state


_KNOWLEDGE_SYSTEM_PROMPT = (
    "You are the Knowledge Agent for Rio CRM.\n"
    "Your job: search the company knowledge base to surface relevant product info,\n"
    "objection rebuttals, competitor intel, playbook guidance, and SOPs.\n\n"
    "Rules:\n"
    "- Always pass company_id to every tool call.\n"
    "- Return only information found in the KB -- do not hallucinate.\n"
    "- Format results as concise bullet points the SDR can use immediately.\n"
    "- If nothing is found, say so clearly rather than guessing."
)


async def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_async_checkpointer
    return create_agent(
        llm,
        tools=KNOWLEDGE_TOOLS,
        system_prompt=_KNOWLEDGE_SYSTEM_PROMPT,
        checkpointer=await get_async_checkpointer(),
    )


@traceable_async(name="run_knowledge_agent", run_type="chain", tags=["knowledge", "rag"])
async def run(
    query: str,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
) -> dict:
    """Run the Knowledge Agent with a natural-language query.

    Args:
        query: What to search for (e.g. "objection handling for price concerns").
        company_id: Tenant ID -- scopes all KB searches.
        actor_user_id: ID of the requesting user (for audit).
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    config = {"configurable": {"thread_id": thread_id or f"knowledge_{company_id}"}}
    with Session(engine) as session:
        llm = get_agent_llm(session, company_id)
    agent = await create_agent(llm, company_id)
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )
        return {"output": result["messages"][-1].content, "errors": []}
    except Exception as exc:
        logger.warning("[KnowledgeAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}

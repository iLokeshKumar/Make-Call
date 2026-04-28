from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async

logger = logging.getLogger(__name__)


@tool
def create_quote(
    lead_id: int, company_id: int, actor_user_id: int,
    items: list, notes: str = "", valid_days: int = 30,
) -> str:
    """Create a new quote for a lead.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the user creating the quote.
        items: List of dicts with product_id, quantity, unit_price keys.
        notes: Optional notes to include on the quote.
        valid_days: Days the quote is valid (default 30).
    """
    try:
        from database import engine
        from sqlmodel import Session
        from models.models import Quote, QuoteItem
        with Session(engine) as session:
            quote = Quote(
                lead_id=lead_id, company_id=company_id,
                created_by=actor_user_id, notes=notes,
                valid_days=valid_days, status="draft",
            )
            session.add(quote)
            session.flush()
            for item in items:
                qi = QuoteItem(
                    quote_id=quote.id, product_id=item.get("product_id"),
                    quantity=item.get("quantity", 1), unit_price=item.get("unit_price", 0),
                )
                session.add(qi)
            session.commit()
            return f"Quote {quote.id} created for lead {lead_id} with {len(items)} item(s)."
    except Exception as exc:
        logger.warning("[QuoteAgent] create_quote failed: %s", exc)
        return f"Quote creation failed: {exc}"


@tool
def send_quote(quote_id: int, company_id: int, actor_user_id: int) -> str:
    """Send a quote to the lead via email and mark it as sent.

    Args:
        quote_id: ID of the quote to send.
        company_id: Tenant ID.
        actor_user_id: ID of the user sending the quote.
    """
    try:
        from database import engine
        from sqlmodel import Session, select
        from models.models import Quote, Lead
        from services.communication.communication_service import send_email_to_lead
        with Session(engine) as session:
            quote = session.exec(
                select(Quote).where(Quote.id == quote_id, Quote.company_id == company_id)
            ).first()
            if not quote:
                return f"Quote {quote_id} not found."
            lead = session.exec(select(Lead).where(Lead.id == quote.lead_id)).first()
            if not lead or not lead.email:
                return "Lead email missing — cannot send quote."
            send_email_to_lead(
                session=session, company_id=company_id, actor_user_id=actor_user_id,
                lead=lead, subject=f"Your Quote #{quote_id}",
                body=f"Please find your quote attached. Valid for {quote.valid_days} days.",
            )
            quote.status = "sent"
            session.add(quote)
            session.commit()
        return f"Quote {quote_id} sent to {lead.email}."
    except Exception as exc:
        logger.warning("[QuoteAgent] send_quote failed: %s", exc)
        return f"Quote send failed: {exc}"


@tool
def get_quote_status(lead_id: int, company_id: int) -> str:
    """Get the status of the most recent quote for a lead.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session, select
        from models.models import Quote
        with Session(engine) as session:
            quote = session.exec(
                select(Quote).where(Quote.lead_id == lead_id, Quote.company_id == company_id)
                .order_by(Quote.created_at.desc())
            ).first()
            if not quote:
                return f"No quotes found for lead {lead_id}."
            return f"Quote {quote.id}: status={quote.status}, created={quote.created_at}"
    except Exception as exc:
        return f"Could not fetch quote: {exc}"


QUOTE_TOOLS = [create_quote, send_quote, get_quote_status]


@traceable(name="quote_node", run_type="chain", tags=['quote'])
def quote_node(state: dict) -> dict:
    """LangGraph node: check quote status for qualified leads with positive outcomes."""
    lead_id = state.get("lead_id")
    company_id = state.get("company_id", 0)
    icp_score = state.get("icp_score", 0.5)
    call_outcome = state.get("call_outcome") or ""

    if not lead_id or icp_score < 0.7 or call_outcome not in ("positive",):
        state.setdefault("agent_results", {})["quote"] = {"skipped": True}
        return state

    status = get_quote_status.invoke({"lead_id": lead_id, "company_id": company_id})
    state.setdefault("agent_results", {})["quote"] = {"status": status}
    return state


_QUOTE_SYSTEM_PROMPT = (
    "You are the Quote Agent for Rio CRM.\n"
    "You create and send product quotes to qualified leads.\n\n"
    "Your tools:\n"
    "- get_quote_status: check if a quote already exists\n"
    "- create_quote: draft a new quote with line items\n"
    "- send_quote: email the quote to the lead and mark it sent\n\n"
    "Rules:\n"
    "- Always call get_quote_status first -- do not create duplicate quotes.\n"
    "- Only create quotes for leads with ICP score >= 0.7 or explicit instruction.\n"
    "- After creating, always call send_quote unless told otherwise."
)


def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_checkpointer
    return create_agent(
        llm,
        tools=QUOTE_TOOLS,
        system_prompt=_QUOTE_SYSTEM_PROMPT,
        checkpointer=get_checkpointer(),
    )


@traceable_async(name="run_quote_agent", run_type="chain", tags=["quote"])
async def run(
    query: str,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
) -> dict:
    """Run the Quote Agent with a natural-language instruction.

    Args:
        query: Instruction (e.g. "Create and send a quote for lead 7 with 3 units of product 2").
        company_id: Tenant ID.
        actor_user_id: ID of the requesting user.
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    config = {"configurable": {"thread_id": thread_id or f"quote_{company_id}"}}
    with Session(engine) as session:
        llm = get_agent_llm(session, company_id)
    agent = create_agent(llm, company_id)
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )
        return {"output": result["messages"][-1].content, "errors": []}
    except Exception as exc:
        logger.warning("[QuoteAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}

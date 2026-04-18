"""
Rio CRM — Live Voice Call Graph  (agents/graph.py)
===================================================

This is the ACTIVE LangGraph chatbot used during real-time voice calls.
It is compiled once at module level as `app` and invoked by voice_pipeline.py
on every conversational turn.

Responsibilities
----------------
- Reads company system prompt + verbosity setting from CompanySetting per turn
- Dynamically selects the LLM (Gemini or Mistral) from company credentials
- Binds the full voice-call tool suite and runs a ReAct loop:
    lookup_product      — inventory / pricing queries
    book_meeting        — schedule a demo/callback
    cancel_meeting      — cancel an existing booking
    send_followup_email — send an email mid-call
    send_personalized_email
    apply_discount      — validate/apply a discount
    get_or_create_lead  — identify/create a lead record from caller phone
    handoff_to_human    — warm-transfer to an ISR
    semantic_query      — search the knowledge base mid-call
    check_lead_status   — look up lead CRM status

Do NOT confuse with:
  agents/orchestrator.py      — master multi-agent workflow (pre/post call)
  agents/langgraph_orchestrator.py — pre/post call shim with fallback nodes
"""
import os
from typing import TypedDict, Annotated, List, Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_mistralai import ChatMistralAI
from dotenv import load_dotenv

# Find project root and load .env
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.abspath(os.path.join(current_dir, "..", ".env"))
load_dotenv(env_path)

from langgraph.graph.message import add_messages

# Define the state
class GraphState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    lead_data: dict
    company_id: Optional[int]   # tenant context for settings lookup

from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from sqlmodel import Session, select
from database import engine
from models.models import CompanySetting, Product, Lead
from utils import settings_cache as _sc
from utils.encryption import decrypt_value
from tools.booking import book_meeting, cancel_meeting
from tools.email import send_followup_email, send_personalized_email
from tools.discount import apply_discount
from tools.query import semantic_query, check_lead_status


def _get_company_setting(session: Session, company_id: int, key: str) -> Optional[str]:
    """Read a CompanySetting for a tenant, using the in-process cache when available."""
    # Try cache first
    cached = _sc.get(key, user_id=company_id)
    if cached is not None:
        return cached
    # Cache miss — hit the DB
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if not row:
        return None
    return decrypt_value(row.value) if row.is_secret else row.value


# AI Engine Factory
def get_dynamic_llm(session: Session, company_id: Optional[int] = None):
    """Fetches the current LLM configuration from CompanySetting and returns the model."""
    if company_id:
        provider_val = (_get_company_setting(session, company_id, "LLM_PROVIDER") or "gemini").lower().strip()
        model_val = _get_company_setting(session, company_id, "LLM_MODEL") or ""
        if not model_val:
            model_val = (
                _get_company_setting(session, company_id, "MISTRAL_MODEL") or "mistral-small-latest"
                if provider_val == "mistral"
                else _get_company_setting(session, company_id, "GEMINI_MODEL") or "gemini-2.0-flash"
            )
    else:
        # No company context — fall back to env vars
        provider_val = os.getenv("LLM_PROVIDER", "gemini").lower().strip()
        model_val = os.getenv("LLM_MODEL", "") or (
            os.getenv("MISTRAL_MODEL", "mistral-small-latest")
            if provider_val == "mistral"
            else os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        )

    if provider_val == "mistral":
        return ChatMistralAI(model=model_val)
    else:
        return ChatGoogleGenerativeAI(model=model_val)

@tool
def lookup_product(query: str):
    """Looks up product information including price and stock level. Use this for any product or pricing queries."""
    print(f"--- TOOL: LOOKUP_PRODUCT ({query}) ---")
    with Session(engine) as session:
        # Case-insensitive search on product name
        statement = select(Product).where(Product.name.ilike(f"%{query}%"))
        results = session.exec(statement).all()
        
        if not results:
            return f"I couldn't find any products matching '{query}' in our inventory."
        
        product_info = []
        for p in results:
            stock_msg = f"{p.stock} units in stock" if p.stock > 0 else "Out of stock"
            item = f"- {p.name}: {p.price} ({stock_msg})"
            if p.note: item += f" | Note: {p.note}"
            product_info.append(item)
            
        return "\n".join(product_info)

@tool
def get_or_create_lead(name: str, phone: str, email: Optional[str] = None, company_id: Optional[int] = None):
    """Looks up a lead by normalized phone number or creates a new one if not found. Use this at the start of a conversation to identify the caller."""
    print(f"--- TOOL: GET_OR_CREATE_LEAD ({phone}) ---")
    with Session(engine) as session:
        statement = select(Lead).where(Lead.normalized_phone == phone)
        lead = session.exec(statement).first()

        if not lead:
            if not company_id:
                return {"error": "company_id is required to create a new lead."}
            print(f"Creating new lead: {name}")
            lead = Lead(name=name, normalized_phone=phone, email=email, company_id=company_id)
            session.add(lead)
            session.commit()
            session.refresh(lead)
            return {"lead_id": lead.id, "name": lead.name, "message": "New lead created."}

        return {"lead_id": lead.id, "name": lead.name, "message": "Existing lead found."}
        
@tool
def handoff_to_human(reason: str):
    """Hands off the conversation to a human agent when the user requests it or the AI cannot help further."""
    print(f"--- TOOL: HANDOFF_TO_HUMAN ({reason}) ---")
    return f"Requesting human assistance: {reason}. A sales representative will be with you shortly."


tools = [
    lookup_product, 
    book_meeting, 
    cancel_meeting, 
    send_followup_email, 
    send_personalized_email, 
    apply_discount,
    get_or_create_lead,
    handoff_to_human,
    semantic_query,
    check_lead_status
]

def chatbot(state: GraphState):
    """
    Invokes the LLM with the current state messages.
    """
    print(f"--- NODE: CHATBOT ---")
    messages = state["messages"]
    company_id: Optional[int] = state.get("company_id")

    with Session(engine) as session:
        # 1. Fetch dynamic settings from CompanySetting (tenant-scoped)
        if company_id:
            system_base = (
                _get_company_setting(session, company_id, "SYSTEM_PROMPT")
                or "You are Rio, a helpful Digital Sales Representative."
            )
            verbosity_level = _get_company_setting(session, company_id, "AI_VERBOSITY") or "2"
        else:
            system_base = "You are Rio, a helpful Digital Sales Representative."
            verbosity_level = "2"

        # 2. Apply Verbosity Rules
        verbosity_rules = {
            "1": "ULTRA-CONCISE: Maximum 5-10 words. Direct answers only. No greetings.",
            "2": "BALANCED: 1-2 sentences. Professional and helpful.",
            "3": "DETAILED: Provide full explanations and helpful context.",
        }
        verbosity_instr = verbosity_rules.get(verbosity_level, verbosity_rules["2"])

        full_system_msg = f"{system_base}\n\nCORE CONSTRAINT: {verbosity_instr}"

        # 3. Ensure System Message is at the TOP (required for Mistral/Gemini stability)
        clean_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]
        final_messages = [SystemMessage(content=full_system_msg)] + clean_messages

        # 4. Get dynamic LLM with tools
        llm = get_dynamic_llm(session, company_id)
        llm_with_tools = llm.bind_tools(tools)

        response = llm_with_tools.invoke(final_messages)

    return {"messages": [response]}

# Build the graph
workflow = StateGraph(GraphState)
workflow.add_node("chatbot", chatbot)
workflow.add_node("tools", ToolNode(tools))

workflow.set_entry_point("chatbot")

# Conditional Edge: Chatbot -> Tools (if tool call) OR End
workflow.add_conditional_edges(
    "chatbot",
    tools_condition,
)

# Edge: Tools -> Chatbot (Loop back)
workflow.add_edge("tools", "chatbot")

# Add persistence
checkpointer = MemorySaver()
app = workflow.compile(checkpointer=checkpointer)

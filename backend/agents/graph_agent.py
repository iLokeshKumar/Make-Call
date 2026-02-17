import os
from typing import TypedDict, Annotated, List, Union, Optional, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.chat_models import FakeListChatModel
from langchain_core.messages import AIMessage
from dotenv import load_dotenv
from langchain_community.chat_models.fake import FakeListChatModel
from langchain_mistralai import ChatMistralAI

# Find project root and load .env
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.abspath(os.path.join(current_dir, "..", ".env"))
load_dotenv(env_path)

from langgraph.graph.message import add_messages

# Define the state
class GraphState(TypedDict):
    messages: Annotated[List[BaseMessage], add_messages]
    lead_data: dict

from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode, tools_condition
from langgraph.checkpoint.memory import MemorySaver
from sqlmodel import Session, select
from backend.database import engine, Product, SystemSettings, Lead
from backend.tools.booking import book_meeting, cancel_meeting
from backend.tools.email import send_followup_email, send_personalized_email
from backend.tools.discount import apply_discount
from backend.tools.query import semantic_query, check_lead_status

# AI Engine Factory
def get_dynamic_llm(session: Session):
    """Fetches the current LLM configuration from the database and returns the model."""
    # Try getting the new Plug & Play keys first
    provider = session.exec(select(SystemSettings).where(SystemSettings.key == "llm_provider")).first()
    model_name = session.exec(select(SystemSettings).where(SystemSettings.key == "llm_model")).first()
    
    # Fallback to old keys if new ones are missing
    if not provider:
        provider = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
    
    provider_val = provider.value.lower().strip() if provider else "gemini"
    model_val = model_name.value.lower().strip() if model_name else ("mistral-small-latest" if provider_val == "mistral" else "gemini-2.0-flash")
    
    print(f"DEBUG: Selected Provider: {provider_val} | Model: {model_val}")
    
    if provider_val == "mistral":
        print(f"Brain: Building Mistral AI ({model_val})")
        return ChatMistralAI(model=model_val)
    else:
        print(f"Brain: Building Google Gemini ({model_val})")
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
def get_or_create_lead(name: str, phone: str, email: Optional[str] = None):
    """Looks up a lead by phone number or creates a new one if not found. Use this at the start of a conversation to identify the user."""
    print(f"--- TOOL: GET_OR_CREATE_LEAD ({phone}) ---")
    with Session(engine) as session:
        statement = select(Lead).where(Lead.phone == phone)
        lead = session.exec(statement).first()
        
        if not lead:
            print(f"Creating new lead: {name}")
            lead = Lead(name=name, phone=phone, email=email)
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
    
    with Session(engine) as session:
        # 1. Fetch dynamic settings
        instr_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
        verbosity_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first()
        
        system_base = instr_setting.value if instr_setting else "You are Rio, a helpful AI sales assistant."
        verbosity_level = verbosity_setting.value if verbosity_setting else "2"
        
        # 2. Apply Verbosity Rules
        verbosity_rules = {
            "1": "ULTRA-CONCISE: Maximum 5-10 words. Direct answers only. No greetings.",
            "2": "BALANCED: 1-2 sentences. Professional and helpful.",
            "3": "DETAILED: Provide full explanations and helpful context."
        }
        verbosity_instr = verbosity_rules.get(verbosity_level, verbosity_rules["2"])
        
        full_system_msg = f"{system_base}\n\nCORE CONSTRAINT: {verbosity_instr}"
        
        # 3. Ensure System Message is at the TOP (Required for Mistral/Gemini stability)
        # Filter out any existing system messages to avoid duplicates/confusion
        clean_messages = [msg for msg in messages if not isinstance(msg, SystemMessage)]
        final_messages = [SystemMessage(content=full_system_msg)] + clean_messages
        
        # 4. Get dynamic LLM with tools
        llm = get_dynamic_llm(session)
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

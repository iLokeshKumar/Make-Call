"""
Unified Tool Adapter for Rio Digital Sales Representative

ARCHITECTURE - This is the CORRECT MCP pattern:
===============================================
1. MCP Tools (mcp_server.py): 
   - Contains @mcp.tool() decorated functions
   - COMPLETE implementations including side effects
   - Example: book_meeting() creates appointment AND sends email
   - Tools are self-contained agents

2. Tool Adapter (this file):
   - Pure schema converter for LLM compatibility
   - Routes tool calls to MCP implementations
   - Does NOT re-implement tool logic
   - Single responsibility: dispatch and schema

3. Main.py:
   - Orchestrates speech recognition → LLM → tools → response flow
   - Calls execute_mcp_tool() when LLM selects a tool

Why this matters:
- Prevents duplicate code in tool_adapter + mcp_server
- Tools are atomic units of work (DB + email together)
- Easy to test: each tool is independent
- Clean separation: logic in MCP, schema in adapter
"""

import logging
from mcp_server import (
    check_icp_qualification,
    get_product_info,
    check_guardrails,
    book_meeting,
    get_call_latency_summary,
    get_or_create_lead,
    sync_product_catalog,
    book_demo,
    send_communication,
    get_google_auth_url,
    submit_google_auth_code
)

logger = logging.getLogger(__name__)

# MISTRAL TOOL SCHEMA CONVERTER

def get_mistral_tools():
    """
    Convert MCP tools to Mistral function calling format.
    
    IMPORTANT: This defines the SCHEMA ONLY
    Actual implementations are in mcp_server.py @mcp.tool() functions
    """
    return [
        {
            "type": "function",
            "function": {
                "name": "check_icp_qualification",
                "description": "Validate if a company qualifies as an ideal customer profile (ICP). Returns qualification score and recommendation.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_size": {
                            "type": "string",
                            "description": "Company size: 'SMB', 'Mid-market', or 'Enterprise'"
                        },
                        "industry": {
                            "type": "string",
                            "description": "Industry: 'Tech', 'Healthcare', 'Finance', 'Retail', or 'Other'"
                        },
                        "employee_count": {
                            "type": "integer",
                            "description": "Number of employees (e.g., 50, 500, 5000)"
                        }
                    },
                    "required": ["company_size", "industry", "employee_count"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_product_info",
                "description": "Fetch accurate product information using semantic search. This tool finds the closest match in the catalog. If a product is not found, treat it as 'temporarily unavailable' and continue the call naturally.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Name or description of the product (e.g., 'Samsung 55 TV', 'Commercial Display')"
                        }
                    },
                    "required": ["product_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "check_guardrails",
                "description": "Check discount limits and approval requirements. Ensures discounts stay within policy.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "requested_discount_percent": {
                            "type": "number",
                            "description": "Requested discount percentage (e.g., 5, 10, 15)"
                        }
                    },
                    "required": ["requested_discount_percent"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "book_meeting",
                "description": "Schedule a meeting/demo for a qualified lead. This is a COMPLETE tool: books appointment AND sends confirmation email to lead. No need to call anything else after this.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {
                            "type": "integer",
                            "description": "Database ID of the lead (e.g., 2 for Lokesh Kumar)"
                        },
                        "proposed_time": {
                            "type": "string",
                            "description": "Proposed meeting time. Preferred format: ISO-8601 (e.g., '2026-03-30T15:00:00'). If unsure, use the raw natural language string (e.g., 'Coming Tuesday at 3 PM')."
                        },
                        "meeting_type": {
                            "type": "string",
                            "description": "Type of meeting: 'demo', 'consultation', 'followup', or 'discovery'"
                        }
                    },
                    "required": ["lead_id", "proposed_time", "meeting_type"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_call_latency_summary",
                "description": "Retrieve detailed latency metrics for a call to identify bottlenecks in STT, LLM, or TTS.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interaction_id": {
                            "type": "integer",
                            "description": "The database ID of the interaction/call."
                        }
                    },
                    "required": ["interaction_id"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_or_create_lead",
                "description": "Identify a lead by phone or create a new record. Use this towards the end of a conversation (e.g., when close to booking or finishing) to identify the user. Avoid calling this at the very start of the call.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Name of the person (e.g., 'John Doe')"
                        },
                        "phone": {
                            "type": "string",
                            "description": "Phone number (e.g., '+1234567890')"
                        },
                        "email": {
                            "type": "string",
                            "description": "Email address (optional)"
                        }
                    },
                    "required": ["name", "phone"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "book_demo",
                "description": "Record a demo request with contact information, location, and product interest. Use this when a lead wants to schedule a demo for specific products.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "integer", "description": "Lead ID"},
                        "name": {"type": "string", "description": "Name of the person"},
                        "phone": {"type": "string", "description": "Phone number"},
                        "city": {"type": "string", "description": "City"},
                        "state": {"type": "string", "description": "State"},
                        "pincode": {"type": "string", "description": "Pincode"},
                        "demo_date": {
                            "type": "string", 
                            "description": "The date and time requested for the demo. Preferred format: ISO-8601 (e.g., '2026-03-30T15:00:00'). If unsure, use the raw natural language string (e.g., 'Tomorrow at 2 PM')."
                        },
                        "products": {"type": "string", "description": "The specific products or services the lead is interested in"},
                        "email": {"type": "string", "description": "Email address (optional)"},
                        "notes": {"type": "string", "description": "Additional requirements (optional)"}
                    },
                    "required": ["lead_id", "name", "phone", "city", "state", "pincode", "demo_date", "products"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "send_communication",
                "description": "Send detailed information (specs, brochures, addresses, etc.) to a lead via Email and/or WhatsApp. Use this whenever a customer asks for information to be shared.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "integer", "description": "Lead ID"},
                        "channels": {
                            "type": "array", 
                            "items": {"type": "string", "enum": ["email", "whatsapp"]},
                            "description": "List of channels to use (e.g., ['email', 'whatsapp'])"
                        },
                        "content": {"type": "string", "description": "The detailed content to be shared with the customer"},
                        "subject": {"type": "string", "description": "Subject line for the communication (primarily for email)"},
                        "email": {"type": "string", "description": "Optional email address (updates the lead and used for sending)"},
                        "phone": {"type": "string", "description": "Optional phone number (updates the lead and used for WhatsApp)"}
                    },
                    "required": ["lead_id", "channels", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "get_google_auth_url",
                "description": "Generate a URL for the user to authorize Rio to access their Google Calendar. Use this if the user asks how to link their account or if book_meeting requires it.",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "submit_google_auth_code",
                "description": "Submit the 12-digit Google authorization code provided by the user after they visit the auth URL.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "The authorization code from Google (e.g. '4/0AdQt8...' )"
                        }
                    },
                    "required": ["code"]
                }
            }
        }
    ]


# UNIFIED TOOL EXECUTOR

async def execute_mcp_tool(tool_name: str, arguments: dict) -> dict:
    """
    Execute MCP tools by delegating to mcp_server.py.
    
    DESIGN PATTERN: This function routes calls to MCP tools.
    It does NOT implement any tool logic - it simply dispatches.
    
    Args:
        tool_name: Name of the tool to execute
        arguments: Dict of arguments for the tool
        
    Returns:
        Tool result as dict
    """
    
    # Hallucination mapping: Mistral sometimes calls 'lookup_product' instead of 'get_product_info'
    if tool_name == "lookup_product":
        tool_name = "get_product_info"
        
    logger.info(f"[execute_mcp_tool] Routing {tool_name} with args: {arguments}")
    
    try:
        if tool_name == "check_icp_qualification":
            # Delegate to MCP tool
            result = check_icp_qualification.fn(
                company_size=arguments.get("company_size"),
                industry=arguments.get("industry"),
                employees=arguments.get("employee_count", 0)
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "get_product_info":
            # Delegate to MCP tool
            result = get_product_info.fn(
                product_name=arguments.get("product_name")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "check_guardrails":
            # Delegate to MCP tool
            result = check_guardrails.fn(
                requested_discount_percent=arguments.get("requested_discount_percent", 0)
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        elif tool_name == "book_meeting":
            # Delegate to MCP tool
            result = await book_meeting.fn(
                lead_id=arguments.get("lead_id"),
                proposed_time=arguments.get("proposed_time"),
                meeting_type=arguments.get("meeting_type", "demo")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "get_call_latency_summary":
            # Delegate to MCP tool
            result = get_call_latency_summary.fn(
                interaction_id=arguments.get("interaction_id")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "get_or_create_lead":
            # Delegate to MCP tool
            result = get_or_create_lead.fn(
                name=arguments.get("name"),
                phone=arguments.get("phone"),
                email=arguments.get("email")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "sync_product_catalog":
            # Delegate to MCP tool
            result = sync_product_catalog.fn()
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "book_demo":
            # Delegate to MCP tool
            result = await book_demo.fn(
                lead_id=arguments.get("lead_id"),
                name=arguments.get("name"),
                phone=arguments.get("phone"),
                city=arguments.get("city"),
                state=arguments.get("state"),
                pincode=arguments.get("pincode"),
                demo_date=arguments.get("demo_date"),
                products=arguments.get("products"),
                email=arguments.get("email"),
                notes=arguments.get("notes")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "send_communication":
            # Delegate to MCP tool
            result = send_communication.fn(
                lead_id=arguments.get("lead_id"),
                channels=arguments.get("channels"),
                content=arguments.get("content"),
                subject=arguments.get("subject", "Message from Rio AI"),
                email=arguments.get("email"),
                phone=arguments.get("phone")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "get_google_auth_url":
            result = get_google_auth_url.fn()
            logger.info(f"[execute_mcp_tool] {tool_name} returned result")
            return result
            
        elif tool_name == "submit_google_auth_code":
            result = submit_google_auth_code.fn(code=arguments.get("code"))
            logger.info(f"[execute_mcp_tool] {tool_name} returned result")
            return result
        
        else:
            error = {
                "available_tools": ["check_icp_qualification", "get_product_info", "check_guardrails", "book_meeting", "get_call_latency_summary", "get_or_create_lead", "sync_product_catalog", "book_demo", "send_communication", "get_google_auth_url", "submit_google_auth_code"]
            }
            logger.error(f"[execute_mcp_tool] Unknown tool error: {error}")
            return error
    
    except Exception as e:
        error = {
            "error": f"Tool execution failed: {str(e)}",
            "tool": tool_name
        }
        logger.error(f"[execute_mcp_tool] Exception: {error}", exc_info=True)
        return error

# TOOL METADATA (for documentation/debugging)

TOOL_DESCRIPTIONS = {
    "check_icp_qualification": {
        "summary": "Validate if a company is ideal customer profile",
        "use_when": "Need to qualify a lead before offering demo",
        "returns": "ICP score, qualification status, priority level"
    },
    "get_product_info": {
        "summary": "Get accurate product details from database",
        "use_when": "Asked about product price, features, or availability",
        "returns": "Product name, price, stock, features",
        "note": "Never make up prices - always use this tool"
    },
    "check_guardrails": {
        "summary": "Check discount limits and approval requirements",
        "use_when": "Lead asks for discount or special pricing",
        "returns": "Approved discount percentage, max allowed, manager approval needed"
    },
    "book_meeting": {
        "summary": "Schedule meeting/demo AND send confirmation email",
        "use_when": "Lead shows interest and wants to move forward",
        "returns": "Appointment ID, calendar URL, email sent status",
        "note": "This is SELF-CONTAINED - handles database + email in one call. No need to call email separately."
    },
    "book_demo": {
        "summary": "Record a demo request with contact information, location, and product interest",
        "use_when": "Lead wants a demo for specific products and provides location",
        "returns": "Demo ID, success status, captured details",
        "note": "Includes automated email confirmation with product details"
    },
    "send_communication": {
        "summary": "Send any requested information via Email and/or WhatsApp",
        "use_when": "Customer asks for specs, brochures, pricing, or any details to be shared",
        "returns": "Success status per channel",
        "note": "Can send to both Email and WhatsApp in one turn if requested"
    }
}

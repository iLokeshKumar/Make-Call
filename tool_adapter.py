"""
Unified Tool Adapter for Rio AI Sales Assistant

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
    book_meeting
)

logger = logging.getLogger(__name__)

# ============================================
# MISTRAL TOOL SCHEMA CONVERTER
# ============================================

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
                "description": "Fetch accurate product information from database. Never guess pricing - always use this tool when asked about products.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_name": {
                            "type": "string",
                            "description": "Name of the product (e.g., 'Voice Assistant', 'CRM Integration', 'Analytics')"
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
                            "description": "Proposed meeting time (e.g., 'Tuesday at 3 PM' or '2026-01-28T15:00:00')"
                        },
                        "meeting_type": {
                            "type": "string",
                            "description": "Type of meeting: 'demo', 'consultation', 'followup', or 'discovery'"
                        }
                    },
                    "required": ["lead_id", "proposed_time", "meeting_type"]
                }
            }
        }
    ]


# ============================================
# UNIFIED TOOL EXECUTOR
# ============================================

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
    
    logger.info(f"[execute_mcp_tool] Routing {tool_name} with args: {arguments}")
    
    try:
        if tool_name == "check_icp_qualification":
            # Delegate to MCP tool
            result = check_icp_qualification(
                company_size=arguments.get("company_size"),
                industry=arguments.get("industry"),
                employees=arguments.get("employee_count", 0)
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "get_product_info":
            # Delegate to MCP tool
            result = get_product_info(
                product_name=arguments.get("product_name")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "check_guardrails":
            # Delegate to MCP tool
            result = check_guardrails(
                requested_discount_percent=arguments.get("requested_discount_percent", 0)
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        elif tool_name == "book_meeting":
            # Delegate to MCP tool (which handles DB + email + logging internally)
            result = book_meeting(
                lead_id=arguments.get("lead_id"),
                proposed_time=arguments.get("proposed_time"),
                meeting_type=arguments.get("meeting_type", "demo")
            )
            logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
            return result
        
        else:
            error = {
                "error": f"Unknown tool: {tool_name}",
                "available_tools": ["check_icp_qualification", "get_product_info", "check_guardrails", "book_meeting"]
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


# ============================================
# TOOL METADATA (for documentation/debugging)
# ============================================

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
    }
}

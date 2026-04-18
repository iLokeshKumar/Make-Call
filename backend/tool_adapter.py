import asyncio
import logging
from typing import Any

from sqlmodel import Session

from database import engine
from services.agent.agent_tool_service import (
    book_demo,
    book_meeting,
    check_guardrails,
    check_icp_qualification,
    get_call_latency_summary,
    get_google_auth_url,
    get_or_create_lead,
    get_product_info,
    get_user_or_404,
    send_communication,
    submit_google_auth_code,
    sync_product_catalog,
)

logger = logging.getLogger(__name__)


def get_mistral_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "check_icp_qualification",
                "description": "Validate whether a prospect fits the ideal customer profile.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_size": {"type": "string"},
                        "industry": {"type": "string"},
                        "employee_count": {"type": "integer"},
                    },
                    "required": ["company_size", "industry", "employee_count"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_product_info",
                "description": "Fetch product details from the tenant's product catalog.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_name": {"type": "string"},
                    },
                    "required": ["product_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_guardrails",
                "description": "Check whether a requested discount is inside policy.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "requested_discount_percent": {"type": "number"},
                    },
                    "required": ["requested_discount_percent"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "book_meeting",
                "description": "Create an appointment for a lead and optionally send confirmation email.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "integer"},
                        "proposed_time": {"type": "string"},
                        "meeting_type": {"type": "string"},
                        "lead_email": {"type": "string"},
                    },
                    "required": ["lead_id", "proposed_time", "meeting_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_call_latency_summary",
                "description": "Return latency summary when analytics migration is available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interaction_id": {"type": "integer"},
                    },
                    "required": ["interaction_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_or_create_lead",
                "description": "Find an existing lead by phone/email or create one in the current tenant.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["name", "phone"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sync_product_catalog",
                "description": "Sync the current tenant's product catalog to the semantic index.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "book_demo",
                "description": "Create a demo appointment for a lead.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "integer"},
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                        "demo_date": {"type": "string"},
                        "products": {"type": "string"},
                        "demo_type": {"type": "string"},
                        "city": {"type": "string"},
                        "state": {"type": "string"},
                        "pincode": {"type": "string"},
                        "email": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["lead_id", "name", "phone", "demo_date", "products", "demo_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_communication",
                "description": "Send an email and/or WhatsApp message to a lead.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"type": "integer"},
                        "channels": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["email", "whatsapp"]},
                        },
                        "content": {"type": "string"},
                        "subject": {"type": "string"},
                        "email": {"type": "string"},
                        "phone": {"type": "string"},
                    },
                    "required": ["lead_id", "channels", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_google_auth_url",
                "description": "Return Google Calendar auth status for the current tenant-safe path.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_google_auth_code",
                "description": "Submit a Google auth code when calendar auth migration is available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                    },
                    "required": ["code"],
                },
            },
        },
    ]


async def _execute_with_session(
    session: Session,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: int | None,
) -> dict[str, Any]:
    if tool_name == "lookup_product":
        tool_name = "get_product_info"

    if tool_name == "check_icp_qualification":
        return check_icp_qualification(
            company_size=arguments.get("company_size", ""),
            industry=arguments.get("industry", ""),
            employee_count=int(arguments.get("employee_count", 0) or 0),
        )

    if not user_id:
        return {
            "error": "Authenticated user context is required for tenant-safe tool execution.",
            "tool": tool_name,
        }

    user = get_user_or_404(session, user_id)
    company_id = user.company_id

    if tool_name == "get_product_info":
        return get_product_info(
            session=session,
            company_id=company_id,
            product_name=arguments.get("product_name", ""),
        )

    if tool_name == "check_guardrails":
        return check_guardrails(
            requested_discount_percent=float(arguments.get("requested_discount_percent", 0) or 0),
        )

    if tool_name == "book_meeting":
        return await book_meeting(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=int(arguments.get("lead_id")),
            proposed_time=arguments.get("proposed_time", ""),
            meeting_type=arguments.get("meeting_type", "demo"),
            lead_email=arguments.get("lead_email"),
        )

    if tool_name == "get_call_latency_summary":
        return get_call_latency_summary(
            interaction_id=int(arguments.get("interaction_id")),
        )

    if tool_name == "get_or_create_lead":
        return get_or_create_lead(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            name=arguments.get("name", ""),
            phone=arguments.get("phone", ""),
            email=arguments.get("email"),
        )

    if tool_name == "sync_product_catalog":
        return sync_product_catalog(
            session=session,
            company_id=company_id,
        )

    if tool_name == "book_demo":
        return await book_demo(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=int(arguments.get("lead_id")),
            name=arguments.get("name", ""),
            phone=arguments.get("phone", ""),
            city=arguments.get("city"),
            state=arguments.get("state"),
            pincode=arguments.get("pincode"),
            demo_date=arguments.get("demo_date", ""),
            products=arguments.get("products", ""),
            demo_type=arguments.get("demo_type", "Offline"),
            email=arguments.get("email"),
            notes=arguments.get("notes"),
        )

    if tool_name == "send_communication":
        return send_communication(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=int(arguments.get("lead_id")),
            channels=list(arguments.get("channels") or []),
            content=arguments.get("content", ""),
            subject=arguments.get("subject"),
            email=arguments.get("email"),
            phone=arguments.get("phone"),
        )

    if tool_name == "get_google_auth_url":
        return get_google_auth_url(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
        )

    if tool_name == "submit_google_auth_code":
        return submit_google_auth_code(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            code=arguments.get("code", ""),
        )

    return {
        "error": "Unknown tool",
        "tool": tool_name,
        "available_tools": [tool["function"]["name"] for tool in get_mistral_tools()],
    }


async def execute_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
    interaction_id: str | None = None,
    user_id: int | None = None,
    user=None,
    session: Session | None = None,
) -> dict[str, Any]:
    logger.info(
        "[execute_mcp_tool] tool=%s interaction_id=%s user_id=%s args=%s",
        tool_name,
        interaction_id,
        user_id,
        arguments,
    )

    try:
        async with asyncio.timeout(30):
            if session is not None:
                effective_user_id = user_id or getattr(user, "id", None)
                return await _execute_with_session(session, tool_name, arguments, effective_user_id)

            with Session(engine) as owned_session:
                effective_user_id = user_id or getattr(user, "id", None)
                return await _execute_with_session(owned_session, tool_name, arguments, effective_user_id)
    except asyncio.TimeoutError:
        logger.error("[execute_mcp_tool] Tool '%s' timed out after 30s", tool_name)
        return {"error": f"Tool '{tool_name}' timed out — please try again.", "tool": tool_name}
    except Exception as exc:
        logger.error("[execute_mcp_tool] Tool execution failed for %s: %s", tool_name, exc, exc_info=True)
        return {
            "error": f"Tool execution failed: {exc}",
            "tool": tool_name,
        }

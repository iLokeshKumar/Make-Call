import asyncio
import logging
import re
from typing import Any

from sqlmodel import Session


# LLM tool-call argument coercion.  Different LLMs handle the same
# function-schema field types differently:
#   - Mistral / GPT-class: clean int or numeric string ("110", 110)
#   - Cerebras Llama 3.1 8B: free-form English ("less than 10", "lead 110", "10%")
#
# Strategy: try the fast path (int()/float()), fall back to regex extraction
# from the string form.  Never reject — pass the result downstream so the
# real tool decides what "valid" means (lead-not-found, etc.).  Keeps the
# original behavior intact for compliant LLMs while catching the messy ones.

def _safe_int_arg(raw: Any, default: int = 0) -> int:
    """Tolerant int coercion for LLM tool args.  Tries int() first; on
    failure, regex-extracts the first integer from the string form.  Returns
    `default` only when nothing numeric is present at all.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    s = str(raw).strip()
    if not s:
        return default
    try:
        return int(s)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+", s)
        return int(m.group(0)) if m else default


def _safe_float_arg(raw: Any, default: float = 0.0) -> float:
    """Tolerant float coercion.  Strips '%', '$', whitespace; extracts the
    first numeric token from strings like '10.5%' or 'discount 15'.  Returns
    `default` only when nothing numeric is present.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("%", "").replace("$", "").strip()
    if not s:
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else default

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


def get_mistral_tools(company_id: int | None = None) -> list[dict[str, Any]]:
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
                        # anyOf accepts both integer and string from any LLM.
                        # Execution coerces via _safe_int_arg regardless of type.
                        "employee_count": {"anyOf": [{"anyOf": [{"type": "integer"}, {"type": "string"}]}, {"type": "string"}]},
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
                        "lead_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
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
                        "interaction_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
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
                        "lead_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
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
                        "lead_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
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
        {
            "type": "function",
            "function": {
                "name": "calendar_book",
                "description": "Book a Google Calendar meeting on behalf of the company. Use this when the customer agrees to schedule a meeting or demo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Meeting title"},
                        "proposed_time": {"type": "string", "description": "ISO 8601 datetime for the meeting start, e.g. 2024-06-10T15:00:00"},
                        "duration_minutes": {"type": "integer", "description": "Duration in minutes (default 30)"},
                        "attendee_email": {"type": "string", "description": "Customer email to invite"},
                        "notes": {"type": "string", "description": "Optional meeting description or agenda"},
                    },
                    "required": ["proposed_time"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "warm_transfer",
                "description": "Transfer the current call to a human agent in a real conference bridge. The customer and the human agent can talk to each other live. Use when the customer asks to speak to a person about pricing, discounts, or escalated issues — and one or more agents are available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "transfer_to_number": {
                            "type": "string",
                            "description": "Optional fallback E.164 phone number only if explicitly provided by system context. The configured Settings number is preferred.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief reason for the transfer (shown to the human agent). Examples: 'customer asked for discount approval', 'escalation — customer is unhappy', 'technical question beyond my knowledge'.",
                        },
                    },
                },
            },
        },
    ]

    if company_id is None:
        return _all_tools

    # Filter to only tools the company has enabled
    try:
        from mcp_tools.tool_catalog import tool_names_for_company
        enabled = tool_names_for_company(company_id)
        return [t for t in _all_tools if t["function"]["name"] in enabled]
    except Exception:
        return _all_tools


async def _execute_with_session(
    session: Session,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: int | None,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    if tool_name == "lookup_product":
        tool_name = "get_product_info"

    if tool_name == "check_icp_qualification":
        return check_icp_qualification(
            company_size=arguments.get("company_size", ""),
            industry=arguments.get("industry", ""),
            employee_count=_safe_int_arg(arguments.get("employee_count")),
        )

    if not user_id:
        return {
            "error": "Authenticated user context is required for tenant-safe tool execution.",
            "tool": tool_name,
        }

    user = get_user_or_404(session, user_id)
    company_id = user.company_id

    # ── Dispatcher fast-path: delegate to registry if tool is registered ──────
    try:
        from mcp_tools.dispatcher import ToolDispatcher
        dispatcher = ToolDispatcher.get()
        if tool_name in dispatcher.registry.list_all():
            int_id = int(interaction_id) if interaction_id and str(interaction_id).isdigit() else None
            return await dispatcher.dispatch(
                tool_name,
                arguments,
                company_id=company_id,
                user_id=user_id,
                interaction_id=int_id,
            )
    except Exception as _disp_exc:
        logger.warning("[tool_adapter] dispatcher check failed, falling through: %s", _disp_exc)
    # ─────────────────────────────────────────────────────────────────────────

    if tool_name == "get_product_info":
        return get_product_info(
            session=session,
            company_id=company_id,
            product_name=arguments.get("product_name", ""),
        )

    if tool_name == "check_guardrails":
        return check_guardrails(
            requested_discount_percent=_safe_float_arg(arguments.get("requested_discount_percent")),
        )

    if tool_name == "book_meeting":
        return await book_meeting(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=_safe_int_arg(arguments.get("lead_id")),
            proposed_time=arguments.get("proposed_time", ""),
            meeting_type=arguments.get("meeting_type", "demo"),
            lead_email=arguments.get("lead_email"),
        )

    if tool_name == "get_call_latency_summary":
        return get_call_latency_summary(
            interaction_id=_safe_int_arg(arguments.get("interaction_id")),
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
            lead_id=_safe_int_arg(arguments.get("lead_id")),
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
            lead_id=_safe_int_arg(arguments.get("lead_id")),
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

    if tool_name == "calendar_book":
        try:
            from routes.calendar import get_company_calendar_credentials
            from google.oauth2.credentials import Credentials  # type: ignore
            import googleapiclient.discovery as _gapi  # type: ignore
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            import uuid as _uuid

            creds = get_company_calendar_credentials(session, company_id)
            if not creds:
                return {"error": "Google Calendar not connected. Ask the user to connect it in Settings."}

            service = _gapi.build("calendar", "v3", credentials=creds)

            # Parse proposed_time — expect ISO 8601 or human string like "2024-06-10T15:00:00"
            proposed_time_str = arguments.get("proposed_time", "")
            try:
                start = _dt.fromisoformat(proposed_time_str.replace("Z", "+00:00"))
            except Exception:
                start = _dt.now(_tz.utc) + _td(hours=24)

            end = start + _td(minutes=int(arguments.get("duration_minutes", 30)))

            event = {
                "summary": arguments.get("title", "Meeting with AI Agent"),
                "description": arguments.get("notes", ""),
                "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
                "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
            }
            attendee_email = arguments.get("attendee_email")
            if attendee_email:
                event["attendees"] = [{"email": attendee_email}]

            created = service.events().insert(calendarId="primary", body=event, sendUpdates="all").execute()
            return {
                "calendar_event_id": created.get("id"),
                "calendar_link": created.get("htmlLink"),
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "status": "booked",
            }
        except Exception as exc:
            logger.error("[calendar_book] Failed: %s", exc, exc_info=True)
            return {"error": f"Calendar booking failed: {exc}"}

    if tool_name == "warm_transfer":
        from credentials_service import get_company_setting_value, get_user_setting_value

        user_transfer_to = get_user_setting_value(session, user.id, "WARM_TRANSFER_NUMBER") or ""
        user_transfer_name = get_user_setting_value(session, user.id, "WARM_TRANSFER_NAME") or ""
        company_transfer_to = get_company_setting_value(session, company_id, "WARM_TRANSFER_NUMBER") or ""
        company_transfer_name = get_company_setting_value(session, company_id, "WARM_TRANSFER_NAME") or ""
        configured_transfer_to = user_transfer_to or company_transfer_to
        configured_transfer_name = user_transfer_name or company_transfer_name
        transfer_to = configured_transfer_to
        reason = arguments.get("reason") or ""
        if not transfer_to:
            return {
                "error": "Warm transfer number is not configured. Add WARM_TRANSFER_NUMBER in Settings > Integration Keys or My Email > My Warm Transfer.",
                "tool": "warm_transfer",
            }
        try:
            from services.call.warm_transfer_service import execute_warm_transfer
            interaction_id_int = int(interaction_id) if interaction_id else 0
            return execute_warm_transfer(
                session=session,
                company_id=company_id,
                actor_user_id=user.id,
                interaction_id=interaction_id_int,
                transfer_to=transfer_to,
                isr_name=configured_transfer_name or reason or None,
            )
        except Exception:
            logger.exception("[warm_transfer] Failed", exc_info=True)
            return {"error": "Warm transfer failed — please try again.", "tool": "warm_transfer"}

    # Route named business capabilities through the capability router
    from services.mcp.capability_router import CAPABILITY_MAP, route_capability
    if tool_name in CAPABILITY_MAP:
        return await route_capability(
            session=session,
            company_id=company_id,
            capability=tool_name,
            arguments=arguments,
            user_id=user_id,
        )

    # Route "<server>__<tool>" calls to the external MCP client
    if "__" in tool_name:
        prefix, ext_tool = tool_name.split("__", 1)
        from services.platform.mcp_client import call_external_tool, EXTERNAL_MCP_SERVERS
        if prefix in EXTERNAL_MCP_SERVERS:
            return await call_external_tool(
                prefix=prefix,
                tool_name=ext_tool,
                arguments=arguments,
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
    import time
    logger.info(
        "[execute_mcp_tool] tool=%s interaction_id=%s user_id=%s args=%s",
        tool_name,
        interaction_id,
        user_id,
        arguments,
    )

    _start = time.monotonic()
    _status = "success"
    _error: str | None = None

    try:
        async with asyncio.timeout(30):
            if session is not None:
                effective_user_id = user_id or getattr(user, "id", None)
                result = await _execute_with_session(session, tool_name, arguments, effective_user_id, interaction_id=interaction_id)
            else:
                with Session(engine) as owned_session:
                    effective_user_id = user_id or getattr(user, "id", None)
                    result = await _execute_with_session(owned_session, tool_name, arguments, effective_user_id, interaction_id=interaction_id)
            if result.get("error"):
                _status = "error"
                _error = str(result["error"])[:500]
            return result
    except asyncio.TimeoutError:
        _status = "timeout"
        _error = f"timed out after 30s"
        logger.error("[execute_mcp_tool] Tool '%s' timed out after 30s", tool_name)
        return {"error": f"Tool '{tool_name}' timed out — please try again.", "tool": tool_name}
    except Exception as exc:
        _status = "error"
        _error = str(exc)[:500]
        logger.error("[execute_mcp_tool] Tool execution failed for %s: %s", tool_name, exc, exc_info=True)
        return {
            "error": f"Tool execution failed: {exc}",
            "tool": tool_name,
        }
    finally:
        _dur_ms = int((time.monotonic() - _start) * 1000)
        try:
            _eid = effective_user_id if "effective_user_id" in dir() else None
            _cid: int | None = None
            if _eid:
                try:
                    with Session(engine) as _s:
                        from models.models import User as _U
                        from sqlmodel import select as _sel
                        _u = _s.exec(_sel(_U).where(_U.id == _eid)).first()
                        _cid = _u.company_id if _u else None
                except Exception:
                    pass
            if _cid:
                from services.observability.tool_call_tracer import trace_tool_call as _trace
                asyncio.create_task(_trace(
                    tool_name=tool_name,
                    company_id=_cid,
                    status=_status,
                    duration_ms=_dur_ms,
                    user_id=_eid,
                    interaction_id=int(interaction_id) if interaction_id and str(interaction_id).isdigit() else None,
                    error_message=_error,
                ))
        except Exception:
            pass

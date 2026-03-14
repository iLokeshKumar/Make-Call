
import asyncio
import logging
from tool_adapter import execute_mcp_tool

logging.basicConfig(level=logging.INFO)

async def test_routing():
    tools_to_test = [
        "check_icp_qualification",
        "get_product_info",
        "check_guardrails",
        "book_meeting",
        "get_call_latency_summary",
        "get_or_create_lead",
        "sync_product_catalog",
        "book_demo",
        "send_communication",
        "get_google_auth_url",
        "submit_google_auth_code"
    ]
    
    print("\n--- Testing Tool Routing ---")
    for tool in tools_to_test:
        print(f"Testing {tool}...")
        # We don't need real args, we just want to see if it routes or hits 'Unknown tool'
        # Some tools might crash if args are missing, but we'll see the 'Unknown' error first if it hits else
        result = await execute_mcp_tool(tool, {})
        if "available_tools" in str(result):
            print(f"❌ FAILED: {tool} hit 'Unknown tool error'")
        elif "error" in str(result) and "execution failed" in str(result).lower():
            print(f"✅ PASSED (Routed correctly, but failed execution due to missing args): {tool}")
        else:
            print(f"✅ PASSED (Routed and returned result): {tool}")

if __name__ == "__main__":
    asyncio.run(test_routing())

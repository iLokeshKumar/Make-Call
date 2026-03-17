import sys
import unittest
from unittest.mock import MagicMock, patch

# Mock mcp_server BEFORE importing tool_adapter
mcp_mock = MagicMock()
sys.modules['mcp_server'] = mcp_mock

import asyncio
from tool_adapter import execute_mcp_tool

class TestToolTypes(unittest.IsolatedAsyncioTestCase):
    async def test_check_guardrails_type(self):
        # Setup mock
        mcp_mock.check_guardrails.fn = MagicMock(return_value={"status": "ok"})
        
        # Test with string input
        await execute_mcp_tool("check_guardrails", {"requested_discount_percent": "10.5"})
        
        # Verify float conversion
        mcp_mock.check_guardrails.fn.assert_called_with(requested_discount_percent=10.5)
        self.assertIsInstance(mcp_mock.check_guardrails.fn.call_args.kwargs['requested_discount_percent'], float)

    async def test_check_icp_qualification_type(self):
        mcp_mock.check_icp_qualification.fn = MagicMock(return_value={"status": "ok"})
        
        await execute_mcp_tool("check_icp_qualification", {
            "company_size": "SMB",
            "industry": "Tech",
            "employee_count": "50"
        })
        
        mcp_mock.check_icp_qualification.fn.assert_called_with(
            company_size="SMB", 
            industry="Tech", 
            employees=50
        )
        self.assertIsInstance(mcp_mock.check_icp_qualification.fn.call_args.kwargs['employees'], int)

    async def test_book_meeting_type(self):
        mcp_mock.book_meeting.fn = MagicMock(return_value={"status": "ok"})
        
        await execute_mcp_tool("book_meeting", {
            "lead_id": "123",
            "proposed_time": "2026-03-30",
            "meeting_type": "demo"
        })
        
        mcp_mock.book_meeting.fn.assert_called_with(
            lead_id=123,
            proposed_time="2026-03-30",
            meeting_type="demo",
            lead_email=None,
            user=None
        )
        self.assertIsInstance(mcp_mock.book_meeting.fn.call_args.kwargs['lead_id'], int)

    async def test_get_call_latency_summary_type(self):
        mcp_mock.get_call_latency_summary.fn = MagicMock(return_value={"status": "ok"})
        
        await execute_mcp_tool("get_call_latency_summary", {"interaction_id": "456"})
        
        mcp_mock.get_call_latency_summary.fn.assert_called_with(interaction_id=456)
        self.assertIsInstance(mcp_mock.get_call_latency_summary.fn.call_args.kwargs['interaction_id'], int)

    async def test_empty_string_handling(self):
        # Test that empty string or None results in 0 (our default in the cast)
        mcp_mock.check_guardrails.fn = MagicMock(return_value={"status": "ok"})
        await execute_mcp_tool("check_guardrails", {"requested_discount_percent": ""})
        mcp_mock.check_guardrails.fn.assert_called_with(requested_discount_percent=0.0)

if __name__ == "__main__":
    unittest.main()

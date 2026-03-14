import sys
import os
from types import SimpleNamespace
import logging

# Add the backend to sys.path so we can import services
sys.path.append(os.getcwd())

from services.llm.base import BaseLLM

# Mock LLM for testing
class MockLLM(BaseLLM):
    async def stream(self, tools=None):
        yield {"type": "finished", "full_reply": "test", "tool_calls": None}

def test_serialization():
    llm = MockLLM("You are a helpful assistant")
    
    # Create a tool call as a SimpleNamespace (this caused the crash)
    tool_call = SimpleNamespace(
        id="call_123",
        function=SimpleNamespace(
            name="get_product_info",
            arguments='{"product_name": "Samsung TV"}'
        )
    )
    
    print(f"Adding tool call of type: {type(tool_call)}")
    llm.add_assistant_message("Let me check that.", tool_calls=[tool_call])
    
    history_msg = llm.messages[-1]
    print(f"Stored message role: {history_msg['role']}")
    print(f"Stored tool_calls type: {type(history_msg['tool_calls'][0])}")
    
    # Verify it is now a dict
    assert isinstance(history_msg['tool_calls'][0], dict), "Tool call should be a dictionary!"
    assert history_msg['tool_calls'][0]['id'] == "call_123"
    assert history_msg['tool_calls'][0]['function']['name'] == "get_product_info"
    
    print("✅ Success: BaseLLM correctly sanitized tool call objects into dictionaries.")

if __name__ == "__main__":
    try:
        test_serialization()
    except Exception as e:
        print(f"❌ Test Failed: {e}")
        sys.exit(1)

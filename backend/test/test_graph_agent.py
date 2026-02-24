import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../")))

from agents.graph_agent import app
from langchain_core.messages import HumanMessage

def run_test():
    print("Starting LangGraph Test...")
    
    # 1. Test Price Check (Tool Call)
    print("\n--- TEST 1: Price Check ---")
    inputs = {"messages": [HumanMessage(content="What is the price of the Samsung S24?")], "lead_data": {}}
    for output in app.stream(inputs):
        for key, value in output.items():
            print(f"Node '{key}':")
            # print(value) 

    # 2. Test Objection (Conversational)
    print("\n--- TEST 2: Objection Handling ---")
    inputs = {"messages": [HumanMessage(content="That is way too expensive for me.")], "lead_data": {}}
    for output in app.stream(inputs):
        for key, value in output.items():
            print(f"Node '{key}':")
            if "messages" in value:
                print(f"Response: {value['messages'][-1].content}")

if __name__ == "__main__":
    run_test()

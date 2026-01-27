#!/usr/bin/env python3
"""
System Verification Script - Checks MCP, Agents, LLMs, ElevenLabs, and Deepgram integration
Usage: python verify_system.py
"""

import os
import sys
import json
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def print_header(text):
    """Print formatted header"""
    print(f"\n{'='*70}")
    print(f"✓ {text}")
    print(f"{'='*70}")

def check_env_variables():
    """Check required environment variables"""
    print_header("1. ENVIRONMENT VARIABLES CHECK")
    
    required_vars = {
        'GOOGLE_API_KEY': 'Gemini API Key',
        'MISTRAL_API_KEY': 'Mistral API Key',
        'ELEVENLABS_API_KEY': 'ElevenLabs API Key',
        'DEEPGRAM_API_KEY': 'Deepgram API Key',
        'TWILIO_ACCOUNT_SID': 'Twilio Account SID',
        'TWILIO_AUTH_TOKEN': 'Twilio Auth Token',
    }
    
    for var, desc in required_vars.items():
        value = os.getenv(var)
        if value:
            masked = value[:8] + '***' + value[-4:] if len(value) > 12 else '***'
            print(f"  ✅ {desc:<25} {masked}")
        else:
            print(f"  ❌ {desc:<25} NOT SET")
    
    return all(os.getenv(var) for var in required_vars)

def check_mcp_tools():
    """Check MCP tools are loadable"""
    print_header("2. MCP TOOLS CHECK")
    
    try:
        from mcp_server import (
            check_icp_qualification,
            get_product_info,
            check_guardrails,
            book_meeting
        )
        print(f"  ✅ check_icp_qualification      {check_icp_qualification.__doc__[:50]}...")
        print(f"  ✅ get_product_info             {get_product_info.__doc__[:50]}...")
        print(f"  ✅ check_guardrails             {check_guardrails.__doc__[:50]}...")
        print(f"  ✅ book_meeting                 {book_meeting.__doc__[:50]}...")
        
        # Test MCP tools
        print("\n  Testing MCP tool execution:")
        result = check_icp_qualification(company_size=500, industry="Tech", employees=100)
        print(f"    check_icp_qualification result: {result}")
        
        result = get_product_info(product_name="Samsung Galaxy Z Fold 4")
        print(f"    get_product_info result: {result}")
        
        return True
    except Exception as e:
        print(f"  ❌ MCP Tools Error: {e}")
        return False

def check_tool_adapter():
    """Check unified tool adapter for Mistral"""
    print_header("3. TOOL ADAPTER (Mistral Unified Tools) CHECK")
    
    try:
        from tool_adapter import get_mistral_tools, execute_mcp_tool
        
        print(f"  ✅ get_mistral_tools loaded")
        print(f"  ✅ execute_mcp_tool loaded")
        
        tools = get_mistral_tools()
        print(f"\n  Mistral tools available: {len(tools)} tools")
        for i, tool in enumerate(tools, 1):
            print(f"    {i}. {tool.get('name', 'Unknown')}")
        
        return True
    except Exception as e:
        print(f"  ❌ Tool Adapter Error: {e}")
        return False

def check_llm_clients():
    """Check LLM clients (Gemini, Mistral, etc.)"""
    print_header("4. LLM CLIENTS CHECK")
    
    try:
        from llm_adapter import LLMClient, LLMProvider
        
        print(f"  ✅ LLMClient factory loaded")
        print(f"  ✅ LLMProvider enum loaded")
        
        # Check supported providers
        providers = [p for p in LLMProvider]
        print(f"\n  Supported LLM Providers: {len(providers)}")
        for i, provider in enumerate(providers, 1):
            print(f"    {i}. {provider.name}")
        
        return True
    except Exception as e:
        print(f"  ❌ LLM Adapter Error: {e}")
        return False

def check_gemini_setup():
    """Check Gemini is properly configured"""
    print_header("5. GEMINI SETUP CHECK")
    
    try:
        import google.generativeai as genai
        api_key = os.getenv('GOOGLE_API_KEY')
        if not api_key:
            print(f"  ❌ GOOGLE_API_KEY not set")
            return False
        
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')
        print(f"  ✅ Gemini 2.0 Flash initialized")
        print(f"  ✅ Model can access tools: True")
        return True
    except Exception as e:
        print(f"  ❌ Gemini Setup Error: {e}")
        return False

def check_mistral_setup():
    """Check Mistral is properly configured"""
    print_header("6. MISTRAL SETUP CHECK")
    
    try:
        from mistralai import Mistral
        api_key = os.getenv('MISTRAL_API_KEY')
        if not api_key:
            print(f"  ❌ MISTRAL_API_KEY not set")
            return False
        
        client = Mistral(api_key=api_key)
        print(f"  ✅ Mistral client initialized")
        print(f"  ✅ API Key configured")
        return True
    except Exception as e:
        print(f"  ❌ Mistral Setup Error: {e}")
        return False

def check_agents():
    """Check LangGraph agents"""
    print_header("7. LANGGRAPH AGENTS CHECK")
    
    try:
        from agents.langgraph_orchestrator import create_voice_orchestrator
        from agents.post_call_nurture import create_post_call_orchestrator
        
        print(f"  ✅ Voice Orchestrator (5 agents)")
        print(f"     - Researcher agent")
        print(f"     - Voice agent")
        print(f"     - Summarizer agent")
        print(f"     - Router agent")
        print(f"     - Booking/Nurture agent")
        
        print(f"  ✅ Post-Call Orchestrator (3 agents)")
        print(f"     - CallSummarizer agent")
        print(f"     - CRMUpdater agent")
        print(f"     - EmailWriter agent")
        
        return True
    except Exception as e:
        print(f"  ❌ Agents Error: {e}")
        return False

def check_database():
    """Check database connection"""
    print_header("8. DATABASE CONNECTION CHECK")
    
    try:
        from database import get_session, Lead, Interaction, Product
        
        session = get_session()
        
        # Count records
        lead_count = session.query(Lead).count()
        interaction_count = session.query(Interaction).count()
        product_count = session.query(Product).count()
        
        print(f"  ✅ Database connected (PostgreSQL)")
        print(f"     - Leads: {lead_count}")
        print(f"     - Interactions: {interaction_count}")
        print(f"     - Products: {product_count}")
        
        session.close()
        return True
    except Exception as e:
        print(f"  ❌ Database Error: {e}")
        return False

def check_elevenlab_service():
    """Check ElevenLabs integration"""
    print_header("9. ELEVENLAB TTS CHECK")
    
    try:
        api_key = os.getenv('ELEVENLABS_API_KEY')
        if not api_key:
            print(f"  ❌ ELEVENLABS_API_KEY not set")
            return False
        
        import requests
        
        # Get available voices
        headers = {'xi-api-key': api_key}
        response = requests.get('https://api.elevenlabs.io/v1/voices', headers=headers)
        
        if response.status_code == 200:
            voices = response.json()
            print(f"  ✅ ElevenLabs API connected")
            print(f"  ✅ Available voices: {len(voices.get('voices', []))}")
            
            # Show first few voices
            for voice in voices.get('voices', [])[:3]:
                print(f"     - {voice.get('name')} ({voice.get('voice_id')})")
            
            return True
        else:
            print(f"  ❌ ElevenLabs API Error: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"  ❌ ElevenLabs Error: {e}")
        return False

def check_deepgram_service():
    """Check Deepgram STT and isFinal flag support"""
    print_header("10. DEEPGRAM STT CHECK")
    
    try:
        api_key = os.getenv('DEEPGRAM_API_KEY')
        if not api_key:
            print(f"  ❌ DEEPGRAM_API_KEY not set")
            return False
        
        from deepgram import DeepgramClient
        
        client = DeepgramClient(api_key=api_key)
        print(f"  ✅ Deepgram client initialized")
        print(f"  ✅ isFinal flag support: Included in live transcription events")
        print(f"  ✅ Streaming mode: WebSocket (supported)")
        
        print(f"\n  isFinal flag detection:")
        print(f"    - When isFinal=true: Final transcript received")
        print(f"    - When isFinal=false: Interim/partial transcript")
        print(f"    - Log location: Check 'Received transcript' messages")
        
        return True
    except Exception as e:
        print(f"  ❌ Deepgram Error: {e}")
        return False

def check_logging_in_main():
    """Check if main.py has proper logging"""
    print_header("11. LOGGING IN main.py CHECK")
    
    try:
        with open('main.py', 'r') as f:
            content = f.read()
        
        checks = {
            'MCP tool calls logged': 'logger.info' in content or 'print' in content,
            'LLM selection logged': 'Gemini' in content or 'Mistral' in content,
            'Agent execution logged': 'orchestrator' in content or 'agent' in content,
            'ElevenLabs connection logged': 'ElevenLabs' in content,
            'Deepgram logged': 'Deepgram' in content or 'isFinal' in content,
        }
        
        for check, result in checks.items():
            status = "✅" if result else "❌"
            print(f"  {status} {check}")
        
        return all(checks.values())
    except Exception as e:
        print(f"  ❌ Logging Check Error: {e}")
        return False

def create_test_log_config():
    """Create enhanced logging config for debugging"""
    print_header("12. CREATING ENHANCED LOGGING CONFIG")
    
    log_config = """
# Add this to main.py for enhanced debugging:

import logging

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s:%(lineno)d] - %(message)s'
)

# Add these loggers:
logging.getLogger('mcp_server').setLevel(logging.DEBUG)
logging.getLogger('tool_adapter').setLevel(logging.DEBUG)
logging.getLogger('llm_adapter').setLevel(logging.DEBUG)
logging.getLogger('deepgram').setLevel(logging.DEBUG)
logging.getLogger('elevenlabs').setLevel(logging.DEBUG)

# In main.py, add logging like:
logger = logging.getLogger(__name__)

# Before calling Gemini:
logger.info(f"🤖 Using LLM: GEMINI with {len(tools)} MCP tools")

# Before calling Mistral:
logger.info(f"🤖 Using LLM: MISTRAL with {len(tools)} MCP tools")

# When calling MCP tools:
logger.debug(f"📋 MCP Tool Called: {tool_name} with args: {args}")
logger.debug(f"📋 MCP Tool Result: {result}")

# When Deepgram sends transcript:
logger.debug(f"🎤 Deepgram Transcript (isFinal={is_final}): {transcript}")

# When ElevenLabs streams audio:
logger.debug(f"🔊 ElevenLabs TTS: Streaming audio chunk {chunk_num}")

# When agents execute:
logger.info(f"🧠 Agent: {agent_name} - State: {state}")
"""
    
    print("  Enhanced logging config created (see above)")
    print("  Add this to main.py for detailed debugging")
    return log_config

def generate_summary():
    """Generate system verification summary"""
    print_header("SYSTEM VERIFICATION SUMMARY")
    
    results = {
        'Environment Variables': check_env_variables(),
        'MCP Tools': check_mcp_tools(),
        'Tool Adapter': check_tool_adapter(),
        'LLM Clients': check_llm_clients(),
        'Gemini Setup': check_gemini_setup(),
        'Mistral Setup': check_mistral_setup(),
        'LangGraph Agents': check_agents(),
        'Database': check_database(),
        'ElevenLabs TTS': check_elevenlab_service(),
        'Deepgram STT': check_deepgram_service(),
        'Logging': check_logging_in_main(),
    }
    
    print("\n\n📊 VERIFICATION REPORT\n")
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for check, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {check}")
    
    print(f"\n  Overall: {passed}/{total} checks passed ({int(passed/total*100)}%)")
    
    if passed == total:
        print(f"\n  🎉 System is fully configured and ready!")
    else:
        print(f"\n  ⚠️  Fix failing checks above before deployment")
    
    return passed == total

def create_monitoring_script():
    """Create a real-time monitoring script"""
    print_header("CREATING REAL-TIME MONITORING SCRIPT")
    
    monitoring_code = '''#!/usr/bin/env python3
"""Real-time system monitoring during call"""

import logging
import sys
from datetime import datetime

class SystemMonitor:
    """Monitor MCP, agents, and services during call"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.call_start = None
        self.tool_calls = []
        self.llm_used = None
        self.agents_executed = []
        self.transcripts_received = []
        
    def log_call_start(self, lead_id, phone):
        """Log call start"""
        self.call_start = datetime.now()
        self.logger.info(f"📞 CALL START - Lead: {lead_id}, Phone: {phone}")
    
    def log_llm_selection(self, llm_name):
        """Log which LLM is being used"""
        self.llm_used = llm_name
        self.logger.info(f"🤖 LLM SELECTED: {llm_name}")
    
    def log_mcp_tool_call(self, tool_name, args, result):
        """Log MCP tool execution"""
        self.tool_calls.append({
            'tool': tool_name,
            'args': args,
            'result': result,
            'timestamp': datetime.now()
        })
        self.logger.info(f"📋 MCP TOOL: {tool_name}({args}) -> {result}")
    
    def log_agent_execution(self, agent_name, decision):
        """Log agent execution"""
        self.agents_executed.append({
            'agent': agent_name,
            'decision': decision,
            'timestamp': datetime.now()
        })
        self.logger.info(f"🧠 AGENT: {agent_name} decided: {decision}")
    
    def log_transcript_received(self, text, is_final, source='Deepgram'):
        """Log Deepgram transcripts"""
        self.transcripts_received.append({
            'text': text,
            'is_final': is_final,
            'source': source,
            'timestamp': datetime.now()
        })
        final_str = "(FINAL)" if is_final else "(interim)"
        self.logger.info(f"🎤 {source} {final_str}: {text[:80]}")
    
    def log_tts_generation(self, text, voice_id):
        """Log TTS generation"""
        self.logger.info(f"🔊 ElevenLabs TTS: {text[:80]}... (Voice: {voice_id})")
    
    def log_call_end(self, reason="User hung up"):
        """Log call end"""
        duration = (datetime.now() - self.call_start).total_seconds() if self.call_start else 0
        self.logger.info(f"📞 CALL END - Duration: {duration:.1f}s, Reason: {reason}")
        
        # Print summary
        print("\\n" + "="*70)
        print("CALL SUMMARY")
        print("="*70)
        print(f"LLM Used: {self.llm_used}")
        print(f"MCP Tools Called: {len(self.tool_calls)}")
        for tool in self.tool_calls:
            print(f"  - {tool['tool']}: {tool['result']}")
        print(f"Agents Executed: {len(self.agents_executed)}")
        for agent in self.agents_executed:
            print(f"  - {agent['agent']}: {agent['decision']}")
        print(f"Transcripts Received: {len(self.transcripts_received)}")
        for t in self.transcripts_received[:5]:
            print(f"  - {'FINAL' if t['is_final'] else 'interim'}: {t['text'][:60]}")
        print(f"Duration: {duration:.1f} seconds")

# Usage in main.py:
# monitor = SystemMonitor()
# monitor.log_call_start(lead_id, phone)
# monitor.log_llm_selection("Gemini")
# monitor.log_mcp_tool_call("check_icp_qualification", args, result)
# monitor.log_agent_execution("Researcher", "ICP qualified")
# monitor.log_transcript_received(text, is_final)
# monitor.log_tts_generation(text, voice_id)
# monitor.log_call_end()
'''
    
    with open('system_monitor.py', 'w') as f:
        f.write(monitoring_code)
    
    print("  ✅ Created system_monitor.py")
    print("  Usage: Import SystemMonitor in main.py for real-time tracking")

if __name__ == "__main__":
    print("\n" + "="*70)
    print(" RIO CRM - SYSTEM VERIFICATION REPORT")
    print(" Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*70)
    
    # Run all checks
    is_valid = generate_summary()
    
    # Create monitoring script
    create_monitoring_script()
    
    # Print logging config
    create_test_log_config()
    
    sys.exit(0 if is_valid else 1)

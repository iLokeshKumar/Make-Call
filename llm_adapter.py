"""
LLM Adapter Factory
Provides pluggable LLM clients for any provider
Enables easy switching between Gemini, Mistral, Qwen, Claude, etc.
"""

from enum import Enum
from typing import Any, Dict
import os


class LLMProvider(Enum):
    """Supported LLM providers"""
    GEMINI = "gemini"
    MISTRAL = "mistral"
    QWEN = "qwen"
    CLAUDE = "claude"
    OPENAI = "openai"
    LLAMA = "llama"


class LLMClient:
    """Universal LLM client interface"""
    
    def __init__(self, provider: LLMProvider, api_key: str = None, **kwargs):
        self.provider = provider
        self.api_key = api_key or self._get_api_key()
        self.config = kwargs
        self.client = self._initialize_client()
    
    def _get_api_key(self) -> str:
        """Get API key from environment"""
        key_map = {
            LLMProvider.GEMINI: "GEMINI_API_KEY",
            LLMProvider.MISTRAL: "MISTRAL_API_KEY",
            LLMProvider.QWEN: "QWEN_API_KEY",
            LLMProvider.CLAUDE: "CLAUDE_API_KEY",
            LLMProvider.OPENAI: "OPENAI_API_KEY",
            LLMProvider.LLAMA: "LLAMA_API_KEY",
        }
        env_var = key_map.get(self.provider)
        return os.getenv(env_var, "")
    
    def _initialize_client(self) -> Any:
        """Initialize the actual LLM client"""
        if self.provider == LLMProvider.GEMINI:
            from google import genai
            return genai.Client(api_key=self.api_key)
        
        elif self.provider == LLMProvider.MISTRAL:
            from mistralai import Mistral
            return Mistral(api_key=self.api_key)
        
        elif self.provider == LLMProvider.QWEN:
            try:
                from dashscope import Generation
                return Generation(api_key=self.api_key)
            except ImportError:
                raise ImportError("Install dashscope: pip install dashscope")
        
        elif self.provider == LLMProvider.CLAUDE:
            try:
                import anthropic
                return anthropic.Anthropic(api_key=self.api_key)
            except ImportError:
                raise ImportError("Install anthropic: pip install anthropic")
        
        elif self.provider == LLMProvider.OPENAI:
            try:
                import openai
                return openai.OpenAI(api_key=self.api_key)
            except ImportError:
                raise ImportError("Install openai: pip install openai")
        
        elif self.provider == LLMProvider.LLAMA:
            try:
                from llama_index.llms import Ollama
                return Ollama(model=self.config.get("model", "llama2"))
            except ImportError:
                raise ImportError("Install llama-index: pip install llama-index")
        
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    @staticmethod
    def get_tools_for_provider(provider: LLMProvider) -> list:
        """Get tool schema for specific LLM provider"""
        from tool_adapter import get_mistral_tools
        
        if provider == LLMProvider.GEMINI:
            # Gemini uses MCP protocol natively
            return []  # MCP server handles it
        
        elif provider == LLMProvider.MISTRAL:
            return get_mistral_tools()
        
        elif provider == LLMProvider.QWEN:
            return get_qwen_tools()
        
        elif provider == LLMProvider.CLAUDE:
            return get_claude_tools()
        
        elif provider == LLMProvider.OPENAI:
            return get_openai_tools()
        
        elif provider == LLMProvider.LLAMA:
            return get_llama_tools()
        
        else:
            raise ValueError(f"Unsupported provider: {provider}")


# ============================================
# FUTURE LLM TOOL CONVERTERS
# ============================================

def get_qwen_tools() -> list:
    """Convert MCP tools to Qwen function calling format"""
    return [
        {
            "type": "function",
            "function": {
                "name": "check_icp_qualification",
                "description": "Validate if a company is ideal customer profile",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_size": {"type": "string"},
                        "industry": {"type": "string"},
                        "employee_count": {"type": "integer"}
                    },
                    "required": ["company_size", "industry", "employee_count"]
                }
            }
        },
        # ... add other tools
    ]


def get_claude_tools() -> list:
    """Convert MCP tools to Claude format"""
    return [
        {
            "name": "check_icp_qualification",
            "description": "Validate if a company is ideal customer profile",
            "input_schema": {
                "type": "object",
                "properties": {
                    "company_size": {"type": "string"},
                    "industry": {"type": "string"},
                    "employee_count": {"type": "integer"}
                },
                "required": ["company_size", "industry", "employee_count"]
            }
        },
        # ... add other tools
    ]


def get_openai_tools() -> list:
    """Convert MCP tools to OpenAI format"""
    return [
        {
            "type": "function",
            "function": {
                "name": "check_icp_qualification",
                "description": "Validate if a company is ideal customer profile",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_size": {"type": "string"},
                        "industry": {"type": "string"},
                        "employee_count": {"type": "integer"}
                    },
                    "required": ["company_size", "industry", "employee_count"]
                }
            }
        },
        # ... add other tools
    ]


def get_llama_tools() -> list:
    """Convert MCP tools to LLaMA format (if supported)"""
    return []  # LLaMA typically runs locally, adjust as needed


# ============================================
# USAGE EXAMPLES
# ============================================

"""
# Switch to Qwen
from llm_adapter import LLMProvider, LLMClient

llm = LLMClient(
    provider=LLMProvider.QWEN,
    api_key="your-qwen-key"
)

# Get tools for the provider
tools = LLMClient.get_tools_for_provider(LLMProvider.QWEN)

# Use in voice pipeline or agents
response = llm.client.chat.complete(...)


# Switch to Claude
llm = LLMClient(provider=LLMProvider.CLAUDE)
tools = LLMClient.get_tools_for_provider(LLMProvider.CLAUDE)


# Switch to OpenAI
llm = LLMClient(provider=LLMProvider.OPENAI)
tools = LLMClient.get_tools_for_provider(LLMProvider.OPENAI)
"""

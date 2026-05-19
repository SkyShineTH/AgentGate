"""Optional adapter helpers for converting external tool-call shapes."""

from agentgate.adapters.base import AdapterError, ToolRequestAdapter
from agentgate.adapters.json_adapter import JsonToolRequestAdapter
from agentgate.adapters.openai import OpenAIFunctionToolCallAdapter

__all__ = [
    "AdapterError",
    "JsonToolRequestAdapter",
    "OpenAIFunctionToolCallAdapter",
    "ToolRequestAdapter",
]

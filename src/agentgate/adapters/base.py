from __future__ import annotations

from typing import Protocol

from agentgate.schemas import ToolRequest


class AdapterError(ValueError):
    """Raised when an adapter cannot normalize a tool-call payload."""


class ToolRequestAdapter(Protocol):
    def to_tool_request(self) -> ToolRequest:
        """Convert an external tool-call shape into AgentGate's canonical request."""


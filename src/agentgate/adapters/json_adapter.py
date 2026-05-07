from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agentgate.adapters.base import AdapterError
from agentgate.schemas import ToolRequest


class JsonToolRequestAdapter:
    """Adapt plain JSON/dict payloads that already match ToolRequest."""

    def __init__(self, payload: object) -> None:
        self.payload = payload

    def to_tool_request(self) -> ToolRequest:
        if not isinstance(self.payload, Mapping):
            raise AdapterError("JSON adapter payload must be an object.")
        try:
            return ToolRequest.model_validate(dict(self.payload))
        except ValidationError as exc:
            raise AdapterError("JSON payload could not be converted to ToolRequest.") from exc

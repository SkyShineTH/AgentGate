from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from agentgate.adapters.base import AdapterError
from agentgate.schemas import ToolRequest


class OpenAIFunctionToolCallAdapter:
    """Adapt an OpenAI-style function tool-call dictionary.

    This module intentionally accepts plain mappings and imports no OpenAI SDK.
    It only normalizes a tested dictionary shape into AgentGate's ToolRequest.
    """

    def __init__(
        self,
        tool_call: object,
        *,
        actor: str,
        resource: str | None = None,
    ) -> None:
        self.tool_call = tool_call
        self.actor = actor
        self.resource = resource

    def to_tool_request(self) -> ToolRequest:
        if not isinstance(self.tool_call, Mapping):
            raise AdapterError("OpenAI-style tool call must be an object.")
        call_id = _string_or_none(self.tool_call.get("id"))
        function = self.tool_call.get("function")
        if not isinstance(function, Mapping):
            raise AdapterError("OpenAI-style tool call must include a function object.")

        name = _string_or_none(function.get("name"))
        if not name:
            raise AdapterError("OpenAI-style function tool call must include a name.")

        arguments = _parse_arguments(function.get("arguments"))
        tool = _required_string(arguments, "tool")
        action = _required_string(arguments, "action")
        resource = self.resource or _required_string(arguments, "resource")
        request_id = _string_or_none(arguments.get("request_id")) or call_id

        input_payload = arguments.get("input", {})
        if not isinstance(input_payload, dict):
            raise AdapterError("OpenAI-style arguments.input must be an object.")

        metadata = arguments.get("metadata", {})
        if not isinstance(metadata, dict):
            raise AdapterError("OpenAI-style arguments.metadata must be an object.")

        metadata = {
            **metadata,
            "adapter": "openai_function_tool_call",
            "provider_tool_name": name,
        }
        if call_id:
            metadata["provider_call_id"] = call_id

        payload: dict[str, Any] = {
            "actor": self.actor,
            "tool": tool,
            "action": action,
            "resource": resource,
            "input": input_payload,
            "metadata": metadata,
        }
        if request_id:
            payload["request_id"] = request_id

        try:
            return ToolRequest.model_validate(payload)
        except ValidationError as exc:
            raise AdapterError(
                "OpenAI-style tool call could not be converted to ToolRequest."
            ) from exc


def _parse_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise AdapterError("OpenAI-style function arguments must be valid JSON.") from exc
    elif isinstance(value, Mapping):
        parsed = dict(value)
    else:
        raise AdapterError("OpenAI-style function arguments must be JSON or an object.")

    if not isinstance(parsed, dict):
        raise AdapterError("OpenAI-style function arguments must decode to an object.")
    return parsed


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = _string_or_none(payload.get(key))
    if not value:
        raise AdapterError(f"OpenAI-style arguments.{key} must be a non-empty string.")
    return value


def _string_or_none(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None

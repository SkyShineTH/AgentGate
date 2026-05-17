from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentgate.schemas import Decision, ToolRequest
from agentgate.secrets import redact


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: f"evt_{uuid4().hex}")
    timestamp: datetime = Field(default_factory=_now_utc)
    event_type: str
    request_id: str
    actor: str | None = None
    tool: str | None = None
    action: str | None = None
    resource: str | None = None
    decision: str | None = None
    reason: str | None = None
    matched_rule: str | None = None
    approval_id: str | None = None
    result_status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(
        self,
        *,
        event_type: str,
        request: ToolRequest | None = None,
        decision: Decision | None = None,
        approval_id: str | None = None,
        result_status: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            event_type=event_type,
            request_id=self._request_id(request, decision),
            actor=request.actor if request else None,
            tool=request.tool if request else None,
            action=request.action if request else None,
            resource=request.resource if request else None,
            decision=decision.status.value if decision else None,
            reason=decision.reason if decision else None,
            matched_rule=decision.matched_rule if decision else None,
            approval_id=approval_id or (decision.approval_id if decision else None),
            result_status=result_status,
            payload=redact(payload or {}),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json(exclude_none=True) + "\n")
        return event

    def read_events(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        events = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(AuditEvent.model_validate_json(line))
        return events

    def list_events(
        self,
        *,
        request_id: str | None = None,
        approval_id: str | None = None,
        event_type: str | None = None,
    ) -> list[AuditEvent]:
        events = self.read_events()
        if request_id is not None:
            events = [event for event in events if event.request_id == request_id]
        if approval_id is not None:
            events = [event for event in events if event.approval_id == approval_id]
        if event_type is not None:
            events = [event for event in events if event.event_type == event_type]
        return events

    @staticmethod
    def _request_id(request: ToolRequest | None, decision: Decision | None) -> str:
        if request:
            return request.request_id
        if decision:
            return decision.request_id
        return "req_unknown"


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

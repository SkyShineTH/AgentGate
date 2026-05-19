from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentgate.schemas import Decision, ToolRequest
from agentgate.secrets import redact

AuditBackend = Literal["jsonl", "sqlite"]
SQLITE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


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
    risk: str | None = None
    reason: str | None = None
    matched_rule: str | None = None
    approval_id: str | None = None
    result_status: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditLog:
    def __init__(self, path: Path, *, backend: AuditBackend | None = None) -> None:
        self.path = path
        self.backend = backend or self._backend_from_path(path)

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
            resource=self._resource(request),
            decision=decision.status.value if decision else None,
            risk=decision.risk.value if decision else None,
            reason=decision.reason if decision else None,
            matched_rule=decision.matched_rule if decision else None,
            approval_id=approval_id or (decision.approval_id if decision else None),
            result_status=result_status,
            payload=redact(payload or {}),
        )
        if self.backend == "sqlite":
            self._append_sqlite(event)
            return event

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.model_dump_json(exclude_none=True) + "\n")
        return event

    def read_events(self) -> list[AuditEvent]:
        if not self.path.exists():
            return []
        if self.backend == "sqlite":
            return self._read_sqlite_events()

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

    @staticmethod
    def _resource(request: ToolRequest | None) -> str | None:
        if request is None:
            return None
        redacted = redact(request.resource)
        return redacted if isinstance(redacted, str) else "[REDACTED]"

    @staticmethod
    def _backend_from_path(path: Path) -> AuditBackend:
        if path.suffix.lower() in SQLITE_SUFFIXES:
            return "sqlite"
        return "jsonl"

    def _append_sqlite(self, event: AuditEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect_sqlite() as conn:
            self._init_sqlite(conn)
            conn.execute(
                """
                INSERT INTO audit_events (
                    event_id,
                    timestamp,
                    event_type,
                    request_id,
                    actor,
                    tool,
                    action,
                    resource,
                    decision,
                    risk,
                    reason,
                    matched_rule,
                    approval_id,
                    result_status,
                    payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.timestamp.isoformat(),
                    event.event_type,
                    event.request_id,
                    event.actor,
                    event.tool,
                    event.action,
                    event.resource,
                    event.decision,
                    event.risk,
                    event.reason,
                    event.matched_rule,
                    event.approval_id,
                    event.result_status,
                    json.dumps(
                        event.payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                ),
            )

    def _read_sqlite_events(self) -> list[AuditEvent]:
        with self._connect_sqlite() as conn:
            self._init_sqlite(conn)
            rows = conn.execute(
                """
                SELECT *
                FROM audit_events
                ORDER BY sequence ASC
                """
            ).fetchall()
        return [self._row_to_event(row) for row in rows]

    def _connect_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _init_sqlite(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                request_id TEXT NOT NULL,
                actor TEXT,
                tool TEXT,
                action TEXT,
                resource TEXT,
                decision TEXT,
                risk TEXT,
                reason TEXT,
                matched_rule TEXT,
                approval_id TEXT,
                result_status TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_request_id
            ON audit_events(request_id, sequence)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_approval_id
            ON audit_events(approval_id, sequence)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_audit_events_event_type
            ON audit_events(event_type, sequence)
            """
        )

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            event_id=row["event_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            event_type=row["event_type"],
            request_id=row["request_id"],
            actor=row["actor"],
            tool=row["tool"],
            action=row["action"],
            resource=row["resource"],
            decision=row["decision"],
            risk=row["risk"],
            reason=row["reason"],
            matched_rule=row["matched_rule"],
            approval_id=row["approval_id"],
            result_status=row["result_status"],
            payload=json.loads(row["payload_json"]),
        )


def load_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

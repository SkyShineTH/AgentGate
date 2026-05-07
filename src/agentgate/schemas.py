from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DecisionStatus(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _new_request_id() -> str:
    return f"req_{uuid4().hex}"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(default_factory=_new_request_id, min_length=1)
    actor: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    action: str = Field(min_length=1)
    resource: str = Field(min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now_utc)

    @field_validator("request_id", "actor", "tool", "action", "resource")
    @classmethod
    def non_blank_string(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    status: DecisionStatus
    risk: RiskLevel
    reason: str
    matched_rule: str
    approval_id: str | None = None

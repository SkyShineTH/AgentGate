from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from agentgate.schemas import DecisionStatus


class PolicyConfigError(ValueError):
    pass


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    private_read: DecisionStatus = DecisionStatus.REQUIRE_APPROVAL
    file_write: DecisionStatus = DecisionStatus.REQUIRE_APPROVAL
    unknown_tool: DecisionStatus = DecisionStatus.DENY
    unknown_action: DecisionStatus = DecisionStatus.DENY
    shell_execute: DecisionStatus = DecisionStatus.DENY
    file_delete: DecisionStatus = DecisionStatus.DENY

    @field_validator("private_read", "file_write")
    @classmethod
    def approval_or_deny(cls, value: DecisionStatus) -> DecisionStatus:
        if value not in {DecisionStatus.REQUIRE_APPROVAL, DecisionStatus.DENY}:
            raise ValueError("must be require_approval or deny")
        return value

    @field_validator("unknown_tool", "unknown_action", "shell_execute", "file_delete")
    @classmethod
    def deny_only(cls, value: DecisionStatus) -> DecisionStatus:
        if value != DecisionStatus.DENY:
            raise ValueError("must be deny")
        return value

    @classmethod
    def from_json_file(cls, path: Path) -> "PolicyConfig":
        try:
            payload: Any = json.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise PolicyConfigError(f"Could not read policy config: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise PolicyConfigError(f"Malformed policy config JSON: {exc.msg}") from exc

        if not isinstance(payload, dict):
            raise PolicyConfigError("Policy config JSON must contain an object.")

        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise PolicyConfigError("Policy config values are invalid.") from exc

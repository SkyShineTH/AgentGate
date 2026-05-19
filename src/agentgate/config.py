from __future__ import annotations

import tomllib
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentgate.policy_config import PolicyConfig, PolicyConfigError


class AgentGateConfigError(ValueError):
    pass


class WorkspaceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_dir: Path | None = None
    public_root: Path | None = None
    private_root: Path | None = None


class AgentGateConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    policy: PolicyConfig = Field(default_factory=PolicyConfig)

    @classmethod
    def from_toml_file(cls, path: Path) -> "AgentGateConfig":
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise AgentGateConfigError(
                f"Could not read AgentGate config: {exc}"
            ) from exc
        except tomllib.TOMLDecodeError as exc:
            raise AgentGateConfigError(
                f"Malformed AgentGate config TOML: {exc}"
            ) from exc

        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            raise AgentGateConfigError("AgentGate config values are invalid.") from exc


def policy_config_from_profile(
    profile: AgentGateConfig,
    *,
    policy_config_path: Path | None = None,
) -> PolicyConfig:
    if policy_config_path is None:
        return profile.policy
    try:
        return PolicyConfig.from_json_file(policy_config_path)
    except PolicyConfigError:
        raise

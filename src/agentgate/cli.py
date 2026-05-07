from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from agentgate.policy import PolicyEngine
from agentgate.schemas import Decision, DecisionStatus, RiskLevel

app = typer.Typer(add_completion=False, help="AgentGate policy gateway CLI.")


@app.callback()
def main() -> None:
    """Evaluate and inspect AgentGate policy decisions."""


@app.command()
def check(request_json: Path) -> None:
    """Evaluate a structured tool request JSON file."""
    try:
        payload = _load_json(request_json)
    except ValueError as exc:
        decision = Decision(
            request_id="req_malformed",
            status=DecisionStatus.DENY,
            risk=RiskLevel.HIGH,
            reason=str(exc),
            matched_rule="malformed_request_denied",
        )
    else:
        decision = PolicyEngine.default().evaluate(payload)

    typer.echo(decision.model_dump_json(indent=2))


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Could not read request JSON: {exc}") from exc

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed JSON request: {exc.msg}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Request JSON must contain an object.")

    return payload

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer
from pydantic import ValidationError

from agentgate.approvals import (
    ApprovalConflict,
    ApprovalNotExecutable,
    ApprovalNotFound,
    ApprovalQueue,
    ApprovalStatus,
    ExecutionStatus,
)
from agentgate.audit import AuditLog
from agentgate.policy import PolicyEngine
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.tools import ToolExecutor

app = typer.Typer(add_completion=False, help="AgentGate policy gateway CLI.")
approvals_app = typer.Typer(help="Manage pending approval requests.")
app.add_typer(approvals_app, name="approvals")

DEFAULT_STATE_DIR = Path(".agentgate")
DEFAULT_APPROVAL_DB = DEFAULT_STATE_DIR / "approvals.sqlite"
DEFAULT_AUDIT_LOG = DEFAULT_STATE_DIR / "audit.jsonl"


@app.callback()
def main() -> None:
    """Evaluate and inspect AgentGate policy decisions."""


@app.command()
def check(
    request_json: Path,
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
    audit_log: Path = typer.Option(
        DEFAULT_AUDIT_LOG,
        "--audit-log",
        help="JSONL audit log path.",
    ),
) -> None:
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
        AuditLog(audit_log).record(event_type="policy_decision", decision=decision)
    else:
        decision = PolicyEngine.default().evaluate(payload)
        request = _parse_request_or_none(payload)
        AuditLog(audit_log).record(
            event_type="policy_decision",
            request=request,
            decision=decision,
            payload={"request": payload},
        )
        if request and decision.status == DecisionStatus.REQUIRE_APPROVAL:
            record = ApprovalQueue(approval_db).create_pending(request, decision)
            decision = record.decision
            AuditLog(audit_log).record(
                event_type="approval_created",
                request=record.request,
                decision=record.decision,
                approval_id=record.approval_id,
            )

    _echo_json(decision)


@approvals_app.command("list")
def list_approvals(
    status: ApprovalStatus | None = typer.Option(
        None,
        "--status",
        help="Filter approvals by status.",
    ),
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
) -> None:
    """List approval records."""
    records = ApprovalQueue(approval_db).list(status)
    typer.echo(
        json.dumps(
            [record.model_dump(mode="json") for record in records],
            indent=2,
        )
    )


@approvals_app.command()
def approve(
    approval_id: str,
    approver: str = typer.Option("human", "--approver", help="Approver name."),
    reason: str | None = typer.Option(None, "--reason", help="Approval reason."),
    request_id: str = typer.Option(
        ...,
        "--request-id",
        help="Expected request_id guard.",
    ),
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
    audit_log: Path = typer.Option(
        DEFAULT_AUDIT_LOG,
        "--audit-log",
        help="JSONL audit log path.",
    ),
) -> None:
    """Approve a pending request-specific approval."""
    try:
        record = ApprovalQueue(approval_db).approve(
            approval_id,
            approver=approver,
            reason=reason,
            expected_request_id=request_id,
        )
    except (ApprovalConflict, ApprovalNotFound) as exc:
        _fail(str(exc))

    AuditLog(audit_log).record(
        event_type="approval_decided",
        request=record.request,
        decision=record.decision,
        approval_id=record.approval_id,
        payload={"approval_status": record.status.value, "decided_by": approver},
    )
    _echo_json(record)


@approvals_app.command()
def reject(
    approval_id: str,
    approver: str = typer.Option("human", "--approver", help="Approver name."),
    reason: str | None = typer.Option(None, "--reason", help="Rejection reason."),
    request_id: str = typer.Option(
        ...,
        "--request-id",
        help="Expected request_id guard.",
    ),
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
    audit_log: Path = typer.Option(
        DEFAULT_AUDIT_LOG,
        "--audit-log",
        help="JSONL audit log path.",
    ),
) -> None:
    """Reject a pending request-specific approval."""
    try:
        record = ApprovalQueue(approval_db).reject(
            approval_id,
            approver=approver,
            reason=reason,
            expected_request_id=request_id,
        )
    except (ApprovalConflict, ApprovalNotFound) as exc:
        _fail(str(exc))

    AuditLog(audit_log).record(
        event_type="approval_decided",
        request=record.request,
        decision=record.decision,
        approval_id=record.approval_id,
        payload={"approval_status": record.status.value, "decided_by": approver},
    )
    _echo_json(record)


@approvals_app.command()
def execute(
    approval_id: str,
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
    audit_log: Path = typer.Option(
        DEFAULT_AUDIT_LOG,
        "--audit-log",
        help="JSONL audit log path.",
    ),
) -> None:
    """Execute the exact stored request for an approved approval."""
    queue = ApprovalQueue(approval_db)
    try:
        request = queue.get_executable_request(approval_id)
    except (ApprovalNotExecutable, ApprovalNotFound) as exc:
        _fail(str(exc))

    result = ToolExecutor.default().execute(request)
    execution_status = ExecutionStatus(result.result_status)
    try:
        record = queue.mark_executed(approval_id, result_status=execution_status)
    except ApprovalNotExecutable as exc:
        _fail(str(exc))

    AuditLog(audit_log).record(
        event_type="executed",
        request=record.request,
        decision=record.decision,
        approval_id=record.approval_id,
        result_status=result.result_status,
        payload={"result": result.model_dump(mode="json")},
    )
    _echo_json(result)


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


def _parse_request_or_none(payload: dict[str, Any]) -> ToolRequest | None:
    try:
        return ToolRequest.model_validate(payload)
    except ValidationError:
        return None


def _echo_json(model: Any) -> None:
    typer.echo(model.model_dump_json(indent=2, exclude_none=True))


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)

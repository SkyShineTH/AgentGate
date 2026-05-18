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
from agentgate.demo import run_personalops_demo
from agentgate.policy import PolicyEngine
from agentgate.policy_config import PolicyConfig, PolicyConfigError
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.tools import ToolExecutor

app = typer.Typer(add_completion=False, help="AgentGate policy gateway CLI.")
approvals_app = typer.Typer(help="Manage pending approval requests.")
audit_app = typer.Typer(help="Inspect audit log events.")
demo_app = typer.Typer(help="Run local synthetic demos.")
app.add_typer(approvals_app, name="approvals")
app.add_typer(audit_app, name="audit")
app.add_typer(demo_app, name="demo")

DEFAULT_STATE_DIR = Path(".agentgate")
DEFAULT_APPROVAL_DB = DEFAULT_STATE_DIR / "approvals.sqlite"
DEFAULT_AUDIT_LOG = DEFAULT_STATE_DIR / "audit.jsonl"
DEFAULT_PERSONALOPS_DEMO_DIR = DEFAULT_STATE_DIR / "personalops-demo"


@app.callback()
def main() -> None:
    """Evaluate and inspect AgentGate policy decisions."""


@app.command()
def check(
    request_json: Path,
    policy_config: Path | None = typer.Option(
        None,
        "--policy-config",
        help="Optional JSON policy profile path.",
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
        decision = _policy_engine(policy_config).evaluate(payload)
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


@audit_app.command("list")
def list_audit_events(
    request_id: str | None = typer.Option(
        None,
        "--request-id",
        help="Filter audit events by request_id.",
    ),
    approval_id: str | None = typer.Option(
        None,
        "--approval-id",
        help="Filter audit events by approval_id.",
    ),
    event_type: str | None = typer.Option(
        None,
        "--event-type",
        help="Filter audit events by event type.",
    ),
    audit_log: Path = typer.Option(
        DEFAULT_AUDIT_LOG,
        "--audit-log",
        help="JSONL audit log path.",
    ),
) -> None:
    """List audit log events."""
    events = AuditLog(audit_log).list_events(
        request_id=request_id,
        approval_id=approval_id,
        event_type=event_type,
    )
    typer.echo(
        json.dumps(
            [event.model_dump(mode="json") for event in events],
            indent=2,
        )
    )


@approvals_app.command("list")
def list_approvals(
    status: ApprovalStatus | None = typer.Option(
        None,
        "--status",
        help="Filter approvals by status.",
    ),
    request_id: str | None = typer.Option(
        None,
        "--request-id",
        help="Filter approvals by request_id.",
    ),
    actor: str | None = typer.Option(
        None,
        "--actor",
        help="Filter approvals by request actor.",
    ),
    tool: str | None = typer.Option(
        None,
        "--tool",
        help="Filter approvals by tool name.",
    ),
    execution_status: ExecutionStatus | None = typer.Option(
        None,
        "--execution-status",
        help="Filter approvals by execution status.",
    ),
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
) -> None:
    """List approval records."""
    records = ApprovalQueue(approval_db).list(
        status,
        request_id=request_id,
        actor=actor,
        tool=tool,
        execution_status=execution_status,
    )
    typer.echo(
        json.dumps(
            [record.model_dump(mode="json") for record in records],
            indent=2,
        )
    )


@approvals_app.command()
def show(
    approval_id: str,
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
) -> None:
    """Show one approval with its current payload and edit summary."""
    queue = ApprovalQueue(approval_db)
    try:
        record = queue.get(approval_id)
    except ApprovalNotFound as exc:
        _fail(str(exc))

    edits = queue.list_edits(approval_id)
    typer.echo(
        json.dumps(
            {
                "approval": record.model_dump(mode="json"),
                "edit_history": _edit_history_summary(edits),
            },
            indent=2,
        )
    )


@approvals_app.command()
def history(
    approval_id: str,
    approval_db: Path = typer.Option(
        DEFAULT_APPROVAL_DB,
        "--approval-db",
        help="SQLite approval queue path.",
    ),
) -> None:
    """List edit history for an approval record."""
    queue = ApprovalQueue(approval_db)
    try:
        queue.get(approval_id)
    except ApprovalNotFound as exc:
        _fail(str(exc))

    edits = queue.list_edits(approval_id)
    typer.echo(
        json.dumps(
            [edit.model_dump(mode="json") for edit in edits],
            indent=2,
        )
    )


@approvals_app.command()
def report(
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
    """Show approval, edit history, and related audit events."""
    queue = ApprovalQueue(approval_db)
    try:
        record = queue.get(approval_id)
    except ApprovalNotFound as exc:
        _fail(str(exc))

    edits = queue.list_edits(approval_id)
    events = _audit_events_for_approval(
        AuditLog(audit_log),
        request_id=record.request_id,
        approval_id=approval_id,
    )
    typer.echo(
        json.dumps(
            {
                "approval": record.model_dump(mode="json"),
                "edit_history": [edit.model_dump(mode="json") for edit in edits],
                "audit_events": [event.model_dump(mode="json") for event in events],
            },
            indent=2,
        )
    )


@approvals_app.command()
def edit(
    approval_id: str,
    request_json: Path,
    editor: str = typer.Option("human", "--editor", help="Editor name."),
    reason: str | None = typer.Option(None, "--reason", help="Edit reason."),
    request_id: str = typer.Option(
        ...,
        "--request-id",
        help="Expected request_id guard.",
    ),
    policy_config: Path | None = typer.Option(
        None,
        "--policy-config",
        help="Optional JSON policy profile path.",
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
    """Replace a pending approval payload with an edited request."""
    try:
        payload = _load_json(request_json)
        edited_request = ToolRequest.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        _fail(f"Invalid edited request: {exc}")

    if edited_request.request_id != request_id:
        _fail("Edited request_id must match --request-id.")

    edited_decision = _policy_engine(policy_config).evaluate(edited_request)
    if edited_decision.status != DecisionStatus.REQUIRE_APPROVAL:
        _fail("Edited request must evaluate to require_approval.")

    try:
        record = ApprovalQueue(approval_db).edit_pending(
            approval_id,
            edited_request,
            edited_decision,
            editor=editor,
            reason=reason,
            expected_request_id=request_id,
        )
    except (ApprovalConflict, ApprovalNotFound) as exc:
        _fail(str(exc))

    AuditLog(audit_log).record(
        event_type="approval_edited",
        request=record.request,
        decision=record.decision,
        approval_id=record.approval_id,
        payload={
            "edited_by": editor,
            "edit_reason": reason,
            "request": record.request.model_dump(mode="json"),
        },
    )
    _echo_json(record)


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
        record = queue.claim_for_execution(approval_id)
    except (ApprovalNotExecutable, ApprovalNotFound) as exc:
        _fail(str(exc))

    result = ToolExecutor.default().execute(record.request, authorized=True)
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


@demo_app.command()
def personalops(
    state_dir: Path = typer.Option(
        DEFAULT_PERSONALOPS_DEMO_DIR,
        "--state-dir",
        help="Runtime state directory for the demo workspace, queue, and audit log.",
    ),
    reset: bool = typer.Option(
        True,
        "--reset/--no-reset",
        help="Reset demo state before running.",
    ),
    auto_approve: bool = typer.Option(
        True,
        "--auto-approve/--no-auto-approve",
        help="Automatically approve the demo write request.",
    ),
) -> None:
    """Run the synthetic PersonalOps approval workflow demo."""
    report = run_personalops_demo(
        state_dir=state_dir,
        reset=reset,
        auto_approve=auto_approve,
    )
    _echo_json(report)


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


def _policy_engine(policy_config_path: Path | None) -> PolicyEngine:
    if policy_config_path is None:
        return PolicyEngine.default()
    try:
        config = PolicyConfig.from_json_file(policy_config_path)
    except PolicyConfigError as exc:
        _fail(str(exc))
    return PolicyEngine(config=config)


def _echo_json(model: Any) -> None:
    typer.echo(model.model_dump_json(indent=2, exclude_none=True))


def _edit_history_summary(edits: list[Any]) -> dict[str, Any]:
    return {
        "count": len(edits),
        "edits": [
            {
                "edit_id": edit.edit_id,
                "edited_at": edit.edited_at.isoformat(),
                "edited_by": edit.edited_by,
                "edit_reason": edit.edit_reason,
            }
            for edit in edits
        ],
    }


def _audit_events_for_approval(
    audit: AuditLog,
    *,
    request_id: str,
    approval_id: str,
) -> list[Any]:
    events = [
        *audit.list_events(request_id=request_id),
        *audit.list_events(approval_id=approval_id),
    ]
    seen: set[str] = set()
    unique_events = []
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        unique_events.append(event)
    return unique_events


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)

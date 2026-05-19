from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentgate.approvals import (
    ApprovalConflict,
    ApprovalNotExecutable,
    ApprovalNotFound,
    ApprovalQueue,
    ApprovalStatus,
    ExecutionStatus,
)
from agentgate.audit import AuditLog
from agentgate.config import AgentGateConfig, AgentGateConfigError
from agentgate.demo import run_personalops_demo
from agentgate.policy import PolicyEngine
from agentgate.policy_config import PolicyConfig, PolicyConfigError
from agentgate.schemas import Decision, DecisionStatus, RiskLevel, ToolRequest
from agentgate.secrets import redact
from agentgate.tools import ExecutionAuthorization, ToolExecutor
from agentgate.workspace import WorkspaceBoundary

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
DEFAULT_AGENTGATE_CONFIG = Path("agentgate.toml")
DEFAULT_EVAL_ROOT = Path("examples")
DEFAULT_PERSONALOPS_DEMO_DIR = DEFAULT_STATE_DIR / "personalops-demo"


@dataclass(frozen=True)
class PolicyRuntime:
    engine: PolicyEngine
    audit_payload: dict[str, Any]


@dataclass(frozen=True)
class WorkspaceRuntime:
    workspace: WorkspaceBoundary
    audit_payload: dict[str, Any]


class EvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    request_id: str
    scenario: str | None = None
    actor: str | None = None
    tool: str | None = None
    action: str | None = None
    resource: str | None = None
    status: str
    risk: str
    matched_rule: str
    reason: str
    expected_status: str | None = None
    expected_risk: str | None = None
    expected_matched_rule: str | None = None
    passed: bool | None = None
    failures: list[str] = Field(default_factory=list)


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_count: int
    counts: dict[str, int] = Field(default_factory=dict)
    expectation_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    results: list[EvalResult]


class EvalExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file: str
    status: str
    risk: str
    matched_rule: str


class EvalExpectationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str | None = None
    cases: list[EvalExpectation]


class AuditRequestSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    actor: str | None = None
    tool: str | None = None
    action: str | None = None
    resource: str | None = None
    approval_ids: list[str] = Field(default_factory=list)
    event_count: int
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None


class AuditDecisionTrailEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    timestamp: datetime
    event_type: str
    decision: str
    risk: str | None = None
    reason: str | None = None
    matched_rule: str | None = None
    approval_id: str | None = None


class AuditApprovalStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    request_id: str
    status: str
    execution_status: str
    decided_by: str | None = None
    decision_reason: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    executed_at: datetime | None = None


class AuditExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    timestamp: datetime
    approval_id: str | None = None
    result_status: str
    result: dict[str, Any] | None = None


class AuditLifecycleReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_summary: AuditRequestSummary
    audit_events: list[dict[str, Any]]
    decision_trail: list[AuditDecisionTrailEntry]
    approvals: list[AuditApprovalStatus] = Field(default_factory=list)
    execution_result: AuditExecutionResult | None = None


@app.callback()
def main() -> None:
    """Evaluate and inspect AgentGate policy decisions."""


@app.command()
def check(
    request_json: Path,
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Optional agentgate.toml profile path.",
    ),
    policy_config: Path | None = typer.Option(
        None,
        "--policy-config",
        help="Optional JSON policy profile path. Overrides [policy] in --config.",
    ),
    workspace_base: Path | None = typer.Option(
        None,
        "--workspace-base",
        help="Base directory for relative request resources.",
    ),
    public_root: Path | None = typer.Option(
        None,
        "--public-root",
        help="Public workspace root for allowed reads.",
    ),
    private_root: Path | None = typer.Option(
        None,
        "--private-root",
        help="Private workspace root for approval-gated reads and writes.",
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
        runtime = _policy_runtime(
            config,
            policy_config_path=policy_config,
            workspace_base=workspace_base,
            public_root=public_root,
            private_root=private_root,
        )
        decision = runtime.engine.evaluate(payload)
        request = _parse_request_or_none(payload)
        AuditLog(audit_log).record(
            event_type="policy_decision",
            request=request,
            decision=decision,
            payload={"request": payload, **runtime.audit_payload},
        )
        if request and decision.status == DecisionStatus.REQUIRE_APPROVAL:
            pending = ApprovalQueue(approval_db).create_pending_result(
                request, decision
            )
            record = pending.record
            decision = record.decision
            AuditLog(audit_log).record(
                event_type=(
                    "approval_created" if pending.created else "approval_existing"
                ),
                request=record.request,
                decision=record.decision,
                approval_id=record.approval_id,
                payload=runtime.audit_payload,
            )

    _echo_json(decision)


@app.command("eval")
def eval_requests(
    requests_path: Path = typer.Option(
        DEFAULT_EVAL_ROOT,
        "--requests-path",
        help="Example request file, requests directory, or examples root.",
    ),
    recursive: bool = typer.Option(
        True,
        "--recursive/--no-recursive",
        help="Find request JSON files recursively under requests directories.",
    ),
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format: json or table.",
    ),
    expectations: Path | None = typer.Option(
        None,
        "--expectations",
        help="Optional eval expectation manifest JSON path.",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Optional agentgate.toml profile path.",
    ),
    policy_config: Path | None = typer.Option(
        None,
        "--policy-config",
        help="Optional JSON policy profile path. Overrides [policy] in --config.",
    ),
    workspace_base: Path | None = typer.Option(
        None,
        "--workspace-base",
        help="Base directory for relative request resources.",
    ),
    public_root: Path | None = typer.Option(
        None,
        "--public-root",
        help="Public workspace root for allowed reads.",
    ),
    private_root: Path | None = typer.Option(
        None,
        "--private-root",
        help="Private workspace root for approval-gated reads and writes.",
    ),
) -> None:
    """Evaluate example requests and summarize policy decisions."""
    if output_format not in {"json", "table"}:
        _fail("--format must be 'json' or 'table'.")

    engine = _policy_runtime(
        config,
        policy_config_path=policy_config,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    ).engine
    request_files = _collect_eval_request_files(requests_path, recursive=recursive)
    if not request_files:
        _fail(f"No request JSON files found under {requests_path}.")

    expectation_index = _load_eval_expectations(expectations)
    results = []
    for request_file in request_files:
        result = _evaluate_request_file(engine, request_file)
        _apply_eval_expectation(
            result, expectation_index.get(_eval_path_key(request_file))
        )
        results.append(result)

    report = EvalReport(
        request_count=len(results),
        counts=_decision_counts(results),
        expectation_count=len(expectation_index),
        passed_count=sum(result.passed is True for result in results),
        failed_count=sum(result.passed is False for result in results),
        results=results,
    )
    if output_format == "table":
        _echo_eval_table(report)
        if report.failed_count:
            raise typer.Exit(code=1)
        return
    _echo_json(report)
    if report.failed_count:
        raise typer.Exit(code=1)


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


@audit_app.command("report")
def audit_report(
    request_id: str | None = typer.Option(
        None,
        "--request-id",
        help="Build a lifecycle report for this request_id.",
    ),
    approval_id: str | None = typer.Option(
        None,
        "--approval-id",
        help="Build a lifecycle report for this approval_id.",
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
    output_format: str = typer.Option(
        "json",
        "--format",
        help="Output format: json or table.",
    ),
) -> None:
    """Show request, decision, approval, and execution audit lifecycle."""
    if output_format not in {"json", "table"}:
        _fail("--format must be 'json' or 'table'.")
    if request_id is None and approval_id is None:
        _fail("Provide --request-id or --approval-id.")

    approval_records = []
    if approval_db.exists():
        approval_records = _approval_records_for_report(
            ApprovalQueue(approval_db),
            request_id=request_id,
            approval_id=approval_id,
        )
    if request_id is None and approval_records:
        request_id = approval_records[0].request_id

    events = _audit_events_for_lifecycle(
        AuditLog(audit_log),
        request_id=request_id,
        approval_id=approval_id,
    )
    if not events and not approval_records:
        _fail("No audit events or approval records matched the report filters.")

    report = AuditLifecycleReport(
        request_summary=_audit_request_summary(
            events,
            approval_records,
            request_id=request_id,
            approval_id=approval_id,
        ),
        audit_events=[event.model_dump(mode="json") for event in events],
        decision_trail=_audit_decision_trail(events),
        approvals=_audit_approval_statuses(approval_records),
        execution_result=_audit_execution_result(events),
    )
    if output_format == "table":
        _echo_audit_report_table(report)
        return
    _echo_json(report)


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
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Optional agentgate.toml profile path.",
    ),
    policy_config: Path | None = typer.Option(
        None,
        "--policy-config",
        help="Optional JSON policy profile path. Overrides [policy] in --config.",
    ),
    workspace_base: Path | None = typer.Option(
        None,
        "--workspace-base",
        help="Base directory for relative request resources.",
    ),
    public_root: Path | None = typer.Option(
        None,
        "--public-root",
        help="Public workspace root for allowed reads.",
    ),
    private_root: Path | None = typer.Option(
        None,
        "--private-root",
        help="Private workspace root for approval-gated reads and writes.",
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

    runtime = _policy_runtime(
        config,
        policy_config_path=policy_config,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    )
    edited_decision = runtime.engine.evaluate(edited_request)
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
            **runtime.audit_payload,
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
    config: Path | None = typer.Option(
        None,
        "--config",
        help="Optional agentgate.toml profile path.",
    ),
    workspace_base: Path | None = typer.Option(
        None,
        "--workspace-base",
        help="Base directory for relative request resources.",
    ),
    public_root: Path | None = typer.Option(
        None,
        "--public-root",
        help="Public workspace root for allowed reads.",
    ),
    private_root: Path | None = typer.Option(
        None,
        "--private-root",
        help="Private workspace root for approval-gated reads and writes.",
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
    """Execute the exact stored request for an approved approval."""
    queue = ApprovalQueue(approval_db)
    try:
        record = queue.claim_for_execution(approval_id)
    except (ApprovalNotExecutable, ApprovalNotFound) as exc:
        _fail(str(exc))

    runtime = _workspace_runtime(
        config,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    )
    authorization = ExecutionAuthorization.from_approval_claim(record)
    result = ToolExecutor(runtime.workspace).execute(
        record.request,
        authorization=authorization,
    )
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
        payload={"result": result.model_dump(mode="json"), **runtime.audit_payload},
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


def _collect_eval_request_files(path: Path, *, recursive: bool) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.exists():
        _fail(f"Request path does not exist: {path}")
    if path.name == "requests":
        return sorted(path.glob("*.json"))
    if recursive:
        return sorted(path.rglob("requests/*.json"))
    return sorted(path.glob("*.json"))


def _evaluate_request_file(engine: PolicyEngine, path: Path) -> EvalResult:
    try:
        payload = _load_json(path)
    except ValueError as exc:
        decision = Decision(
            request_id="req_malformed",
            status=DecisionStatus.DENY,
            risk=RiskLevel.HIGH,
            reason=str(exc),
            matched_rule="malformed_request_denied",
        )
        return EvalResult(
            file=str(path),
            request_id=decision.request_id,
            status=decision.status.value,
            risk=decision.risk.value,
            matched_rule=decision.matched_rule,
            reason=decision.reason,
        )

    decision = engine.evaluate(payload)
    request = _parse_request_or_none(payload)
    return EvalResult(
        file=str(path),
        request_id=decision.request_id,
        scenario=_metadata_value(request, "scenario"),
        actor=request.actor if request else None,
        tool=request.tool if request else None,
        action=request.action if request else None,
        resource=request.resource if request else None,
        status=decision.status.value,
        risk=decision.risk.value,
        matched_rule=decision.matched_rule,
        reason=decision.reason,
    )


def _load_eval_expectations(path: Path | None) -> dict[str, EvalExpectation]:
    if path is None:
        return {}
    try:
        payload = _load_json(path)
        manifest = EvalExpectationManifest.model_validate(payload)
    except (ValueError, ValidationError) as exc:
        _fail(f"Invalid eval expectations: {exc}")

    expectations: dict[str, EvalExpectation] = {}
    for case in manifest.cases:
        expectation_path = Path(case.file)
        if expectation_path.is_absolute():
            resolved = expectation_path
        else:
            resolved = Path.cwd() / expectation_path
        expectations[_eval_path_key(resolved)] = case
    return expectations


def _apply_eval_expectation(
    result: EvalResult,
    expectation: EvalExpectation | None,
) -> None:
    if expectation is None:
        return

    failures = []
    if result.status != expectation.status:
        failures.append(f"status expected {expectation.status}, got {result.status}")
    if result.risk != expectation.risk:
        failures.append(f"risk expected {expectation.risk}, got {result.risk}")
    if result.matched_rule != expectation.matched_rule:
        failures.append(
            f"matched_rule expected {expectation.matched_rule}, "
            f"got {result.matched_rule}"
        )

    result.expected_status = expectation.status
    result.expected_risk = expectation.risk
    result.expected_matched_rule = expectation.matched_rule
    result.failures = failures
    result.passed = not failures


def _eval_path_key(path: Path) -> str:
    return str(path.resolve(strict=False)).replace("\\", "/")


def _metadata_value(request: ToolRequest | None, key: str) -> str | None:
    if request is None:
        return None
    value = request.metadata.get(key)
    return value if isinstance(value, str) else None


def _decision_counts(results: list[EvalResult]) -> dict[str, int]:
    counts = {
        DecisionStatus.ALLOW.value: 0,
        DecisionStatus.REQUIRE_APPROVAL.value: 0,
        DecisionStatus.DENY.value: 0,
    }
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _echo_eval_table(report: EvalReport) -> None:
    rows = [
        (
            _eval_pass_label(result),
            result.status,
            result.risk,
            result.matched_rule,
            result.request_id,
            Path(result.file).name,
        )
        for result in report.results
    ]
    headers = ("PASS", "STATUS", "RISK", "RULE", "REQUEST_ID", "FILE")
    widths = [
        max(len(str(row[index])) for row in [headers, *rows])
        for index in range(len(headers))
    ]
    lines = [
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(headers)),
        "-+-".join("-" * width for width in widths),
    ]
    lines.extend(
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in rows
    )
    lines.append("")
    lines.append(
        "Counts: "
        + ", ".join(f"{status}={count}" for status, count in report.counts.items())
    )
    if report.expectation_count:
        lines.append(
            "Expectations: "
            f"checked={report.expectation_count}, "
            f"passed={report.passed_count}, "
            f"failed={report.failed_count}"
        )
    typer.echo("\n".join(lines))


def _echo_audit_report_table(report: AuditLifecycleReport) -> None:
    summary = report.request_summary
    lines = [
        "REQUEST SUMMARY",
        *_format_table(
            ("FIELD", "VALUE"),
            [
                ("request_id", summary.request_id),
                ("actor", summary.actor or "-"),
                ("tool", summary.tool or "-"),
                ("action", summary.action or "-"),
                ("resource", summary.resource or "-"),
                ("approval_ids", ", ".join(summary.approval_ids) or "-"),
                ("event_count", str(summary.event_count)),
            ],
        ),
        "",
        "AUDIT EVENTS",
        *_format_table(
            ("TIME", "EVENT", "DECISION", "RISK", "RULE", "APPROVAL", "RESULT"),
            [
                (
                    event.get("timestamp", "-"),
                    event.get("event_type", "-"),
                    event.get("decision") or "-",
                    event.get("risk") or "-",
                    event.get("matched_rule") or "-",
                    event.get("approval_id") or "-",
                    event.get("result_status") or "-",
                )
                for event in report.audit_events
            ],
        ),
        "",
        "DECISION TRAIL",
        *_format_table(
            ("TIME", "DECISION", "RISK", "RULE", "REASON"),
            [
                (
                    item.timestamp.isoformat(),
                    item.decision,
                    item.risk or "-",
                    item.matched_rule or "-",
                    item.reason or "-",
                )
                for item in report.decision_trail
            ],
        ),
        "",
        "APPROVALS",
        *_format_table(
            ("APPROVAL_ID", "STATUS", "EXECUTION", "DECIDED_BY"),
            [
                (
                    item.approval_id,
                    item.status,
                    item.execution_status,
                    item.decided_by or "-",
                )
                for item in report.approvals
            ],
        ),
        "",
        "EXECUTION RESULT",
        *_format_table(
            ("FIELD", "VALUE"),
            _audit_execution_result_rows(report.execution_result),
        ),
    ]
    typer.echo("\n".join(lines))


def _audit_execution_result_rows(
    result: AuditExecutionResult | None,
) -> list[tuple[str, str]]:
    if result is None:
        return [("result_status", "-")]

    payload = result.result or {}
    return [
        ("result_status", result.result_status),
        ("approval_id", result.approval_id or "-"),
        ("tool", str(payload.get("tool") or "-")),
        ("action", str(payload.get("action") or "-")),
        ("resource", str(payload.get("resource") or "-")),
        ("message", str(payload.get("message") or "-")),
    ]


def _format_table(headers: tuple[str, ...], rows: list[tuple[str, ...]]) -> list[str]:
    normalized_rows = rows or [tuple("-" for _ in headers)]
    widths = [
        max(len(str(row[index])) for row in [headers, *normalized_rows])
        for index in range(len(headers))
    ]
    return [
        " | ".join(value.ljust(widths[index]) for index, value in enumerate(headers)),
        "-+-".join("-" * width for width in widths),
        *(
            " | ".join(
                str(value).ljust(widths[index]) for index, value in enumerate(row)
            )
            for row in normalized_rows
        ),
    ]


def _eval_pass_label(result: EvalResult) -> str:
    if result.passed is True:
        return "pass"
    if result.passed is False:
        return "fail"
    return "-"


def _parse_request_or_none(payload: dict[str, Any]) -> ToolRequest | None:
    try:
        return ToolRequest.model_validate(payload)
    except ValidationError:
        return None


def _policy_engine(
    config_path: Path | None,
    *,
    policy_config_path: Path | None = None,
    workspace_base: Path | None = None,
    public_root: Path | None = None,
    private_root: Path | None = None,
) -> PolicyEngine:
    return _policy_runtime(
        config_path,
        policy_config_path=policy_config_path,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    ).engine


def _policy_runtime(
    config_path: Path | None,
    *,
    policy_config_path: Path | None = None,
    workspace_base: Path | None = None,
    public_root: Path | None = None,
    private_root: Path | None = None,
) -> PolicyRuntime:
    profile, profile_path = _load_agentgate_config(config_path)
    workspace_runtime = _workspace_runtime_from_profile(
        profile,
        profile_path=profile_path,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    )
    try:
        policy_config = (
            PolicyConfig.from_json_file(policy_config_path)
            if policy_config_path is not None
            else profile.policy
        )
    except PolicyConfigError as exc:
        _fail(str(exc))
    policy_source, policy_path = _policy_source(profile_path, policy_config_path)
    return PolicyRuntime(
        engine=PolicyEngine(
            workspace=workspace_runtime.workspace,
            config=policy_config,
        ),
        audit_payload={
            "policy_source": policy_source,
            **_optional_path_payload("policy_path", policy_path),
            **workspace_runtime.audit_payload,
        },
    )


def _workspace_boundary(
    config_path: Path | None,
    *,
    workspace_base: Path | None = None,
    public_root: Path | None = None,
    private_root: Path | None = None,
) -> WorkspaceBoundary:
    return _workspace_runtime(
        config_path,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    ).workspace


def _workspace_runtime(
    config_path: Path | None,
    *,
    workspace_base: Path | None = None,
    public_root: Path | None = None,
    private_root: Path | None = None,
) -> WorkspaceRuntime:
    profile, profile_path = _load_agentgate_config(config_path)
    return _workspace_runtime_from_profile(
        profile,
        profile_path=profile_path,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    )


def _load_agentgate_config(
    config_path: Path | None,
) -> tuple[AgentGateConfig, Path | None]:
    if config_path is None:
        if not DEFAULT_AGENTGATE_CONFIG.exists():
            return AgentGateConfig(), None
        config_path = DEFAULT_AGENTGATE_CONFIG

    try:
        return AgentGateConfig.from_toml_file(config_path), config_path
    except AgentGateConfigError as exc:
        _fail(str(exc))


def _workspace_boundary_from_profile(
    profile: AgentGateConfig,
    *,
    profile_path: Path | None,
    workspace_base: Path | None,
    public_root: Path | None,
    private_root: Path | None,
) -> WorkspaceBoundary:
    return _workspace_runtime_from_profile(
        profile,
        profile_path=profile_path,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    ).workspace


def _workspace_runtime_from_profile(
    profile: AgentGateConfig,
    *,
    profile_path: Path | None,
    workspace_base: Path | None,
    public_root: Path | None,
    private_root: Path | None,
) -> WorkspaceRuntime:
    workspace_config = profile.workspace
    has_custom_workspace = any(
        value is not None
        for value in (
            workspace_config.base_dir,
            workspace_config.public_root,
            workspace_config.private_root,
            workspace_base,
            public_root,
            private_root,
        )
    )
    if not has_custom_workspace:
        workspace = WorkspaceBoundary.default()
        return WorkspaceRuntime(
            workspace=workspace,
            audit_payload=_workspace_audit_payload(
                source="default",
                source_path=None,
                workspace=workspace,
            ),
        )

    profile_origin = profile_path.parent if profile_path is not None else Path.cwd()
    base_dir = _resolve_path(
        workspace_base or workspace_config.base_dir or Path.cwd(),
        origin=Path.cwd() if workspace_base is not None else profile_origin,
    )
    resolved_public_root = _resolve_workspace_root(
        public_root
        or workspace_config.public_root
        or Path("examples/workspace/public"),
        base_dir=base_dir,
        origin=Path.cwd() if public_root is not None else profile_origin,
    )
    resolved_private_root = _resolve_workspace_root(
        private_root
        or workspace_config.private_root
        or Path("examples/workspace/private"),
        base_dir=base_dir,
        origin=Path.cwd() if private_root is not None else profile_origin,
    )
    workspace = WorkspaceBoundary(
        base_dir=base_dir,
        public_root=resolved_public_root,
        private_root=resolved_private_root,
    )
    workspace_source, workspace_path = _workspace_source(
        profile,
        profile_path=profile_path,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    )
    return WorkspaceRuntime(
        workspace=workspace,
        audit_payload=_workspace_audit_payload(
            source=workspace_source,
            source_path=workspace_path,
            workspace=workspace,
        ),
    )


def _resolve_workspace_root(path: Path, *, base_dir: Path, origin: Path) -> Path:
    if path.is_absolute():
        return path
    origin_candidate = origin / path
    if origin_candidate.exists():
        return origin_candidate
    return base_dir / path


def _resolve_path(path: Path, *, origin: Path) -> Path:
    if path.is_absolute():
        return path
    return origin / path


def _policy_source(
    profile_path: Path | None,
    policy_config_path: Path | None,
) -> tuple[str, Path | None]:
    if policy_config_path is not None:
        return "policy_config", policy_config_path
    if profile_path is not None:
        return "agentgate.toml", profile_path
    return "default", None


def _workspace_source(
    profile: AgentGateConfig,
    *,
    profile_path: Path | None,
    workspace_base: Path | None,
    public_root: Path | None,
    private_root: Path | None,
) -> tuple[str, Path | None]:
    if any(value is not None for value in (workspace_base, public_root, private_root)):
        return "cli", None
    if profile_path is not None and any(
        value is not None
        for value in (
            profile.workspace.base_dir,
            profile.workspace.public_root,
            profile.workspace.private_root,
        )
    ):
        return "agentgate.toml", profile_path
    return "default", None


def _workspace_audit_payload(
    *,
    source: str,
    source_path: Path | None,
    workspace: WorkspaceBoundary,
) -> dict[str, Any]:
    return {
        "workspace_source": source,
        **_optional_path_payload("workspace_path", source_path),
        "workspace_roots": {
            "base_dir": _redacted_path(workspace.base_dir),
            "public_root": _redacted_path(workspace.public_root),
            "private_root": _redacted_path(workspace.private_root),
        },
    }


def _optional_path_payload(key: str, path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    return {key: _redacted_path(path)}


def _redacted_path(path: Path) -> str:
    redacted = redact(str(path.resolve(strict=False)))
    return redacted if isinstance(redacted, str) else "[REDACTED]"


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


def _approval_records_for_report(
    queue: ApprovalQueue,
    *,
    request_id: str | None,
    approval_id: str | None,
) -> list[Any]:
    records = []
    if request_id is not None:
        records.extend(queue.list(request_id=request_id))
    if approval_id is not None:
        try:
            records.append(queue.get(approval_id))
        except ApprovalNotFound:
            pass

    seen: set[str] = set()
    unique_records = []
    for record in records:
        if record.approval_id in seen:
            continue
        seen.add(record.approval_id)
        unique_records.append(record)
    return unique_records


def _audit_events_for_lifecycle(
    audit: AuditLog,
    *,
    request_id: str | None,
    approval_id: str | None,
) -> list[Any]:
    events = []
    if request_id is not None:
        events.extend(audit.list_events(request_id=request_id))
    if approval_id is not None:
        events.extend(audit.list_events(approval_id=approval_id))
    return _unique_ordered_audit_events(events)


def _audit_request_summary(
    events: list[Any],
    approval_records: list[Any],
    *,
    request_id: str | None,
    approval_id: str | None,
) -> AuditRequestSummary:
    event = next((item for item in events if item.actor or item.tool), None)
    record = approval_records[0] if approval_records else None
    approval_ids = sorted(
        {
            item
            for item in [
                approval_id,
                *(event.approval_id for event in events),
                *(record.approval_id for record in approval_records),
            ]
            if item is not None
        }
    )
    return AuditRequestSummary(
        request_id=(
            request_id
            or (event.request_id if event else None)
            or (record.request_id if record else None)
            or "req_unknown"
        ),
        actor=(event.actor if event else None)
        or (record.request.actor if record else None),
        tool=(event.tool if event else None)
        or (record.request.tool if record else None),
        action=(event.action if event else None)
        or (record.request.action if record else None),
        resource=(event.resource if event else None)
        or (_redacted_value(record.request.resource) if record else None),
        approval_ids=approval_ids,
        event_count=len(events),
        first_event_at=events[0].timestamp if events else None,
        last_event_at=events[-1].timestamp if events else None,
    )


def _audit_decision_trail(events: list[Any]) -> list[AuditDecisionTrailEntry]:
    return [
        AuditDecisionTrailEntry(
            event_id=event.event_id,
            timestamp=event.timestamp,
            event_type=event.event_type,
            decision=event.decision,
            risk=event.risk,
            reason=event.reason,
            matched_rule=event.matched_rule,
            approval_id=event.approval_id,
        )
        for event in events
        if event.decision is not None
    ]


def _audit_approval_statuses(records: list[Any]) -> list[AuditApprovalStatus]:
    return [
        AuditApprovalStatus(
            approval_id=record.approval_id,
            request_id=record.request_id,
            status=record.status.value,
            execution_status=record.execution_status.value,
            decided_by=record.decided_by,
            decision_reason=record.decision_reason,
            created_at=record.created_at,
            decided_at=record.decided_at,
            executed_at=record.executed_at,
        )
        for record in records
    ]


def _audit_execution_result(events: list[Any]) -> AuditExecutionResult | None:
    executed_events = [event for event in events if event.result_status is not None]
    if not executed_events:
        return None

    event = executed_events[-1]
    result = event.payload.get("result")
    return AuditExecutionResult(
        event_id=event.event_id,
        timestamp=event.timestamp,
        approval_id=event.approval_id,
        result_status=event.result_status,
        result=result if isinstance(result, dict) else None,
    )


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
    return _unique_ordered_audit_events(unique_events)


def _unique_ordered_audit_events(events: list[Any]) -> list[Any]:
    seen: set[str] = set()
    unique_events = []
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        unique_events.append(event)
    return sorted(unique_events, key=lambda event: event.timestamp)


def _redacted_value(value: Any) -> Any:
    redacted = redact(value)
    return redacted if isinstance(redacted, str) else "[REDACTED]"


def _fail(message: str) -> None:
    typer.echo(message, err=True)
    raise typer.Exit(code=1)

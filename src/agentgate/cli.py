from __future__ import annotations

import json
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
        decision = _policy_engine(
            config,
            policy_config_path=policy_config,
            workspace_base=workspace_base,
            public_root=public_root,
            private_root=private_root,
        ).evaluate(payload)
        request = _parse_request_or_none(payload)
        AuditLog(audit_log).record(
            event_type="policy_decision",
            request=request,
            decision=decision,
            payload={"request": payload},
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

    engine = _policy_engine(
        config,
        policy_config_path=policy_config,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    )
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

    edited_decision = _policy_engine(
        config,
        policy_config_path=policy_config,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    ).evaluate(edited_request)
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

    workspace = _workspace_boundary(
        config,
        workspace_base=workspace_base,
        public_root=public_root,
        private_root=private_root,
    )
    authorization = ExecutionAuthorization.from_approval_claim(record)
    result = ToolExecutor(workspace).execute(
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
    profile, profile_path = _load_agentgate_config(config_path)
    workspace = _workspace_boundary_from_profile(
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
    return PolicyEngine(workspace=workspace, config=policy_config)


def _workspace_boundary(
    config_path: Path | None,
    *,
    workspace_base: Path | None = None,
    public_root: Path | None = None,
    private_root: Path | None = None,
) -> WorkspaceBoundary:
    profile, profile_path = _load_agentgate_config(config_path)
    return _workspace_boundary_from_profile(
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
        return WorkspaceBoundary.default()

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
    return WorkspaceBoundary(
        base_dir=base_dir,
        public_root=resolved_public_root,
        private_root=resolved_private_root,
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

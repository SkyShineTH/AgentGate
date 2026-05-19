# Roadmap

Last updated: 2026-05-19

Roadmap entries must not imply shipped functionality. Use `Planned`,
`Exploring`, or `Open Question` labels until implementation and tests exist.

## Phase 0: Context and Scaffolding

Status: Implemented

Goals:

- Establish project thesis.
- Add agent instructions and detailed docs.
- Set provider-agnostic architecture direction.
- Keep initial repo simple.

Exit criteria:

- README links to project context.
- `AGENTS.md` exists.
- Architecture, policy, security, testing, roadmap, and references docs exist.

## Phase 1: Core Policy Gateway

Status: Implemented

Goals:

- Add Python package structure.
- Define canonical `ToolRequest` and `Decision` schemas.
- Implement deterministic policy engine.
- Implement workspace path boundary checks.
- Implement JSONL audit logging.
- Add CLI command to check request files.

Exit criteria:

- Safe public read returns `allow`.
- Private read returns `require_approval` or `deny`, depending on policy.
- File write returns `require_approval`.
- Delete returns `deny`.
- Shell returns `deny` by default.
- Tests cover those decisions.

## Phase 2: Approval Queue

Status: Implemented

Implemented notes:

- Approval-required requests are stored in a local SQLite queue.
- CLI commands can list, approve, reject, and execute approved requests.
- Approved execution uses the exact stored request payload.
- JSONL audit events record policy decisions, approval creation, approval
  decisions, and execution results.
- The local executor supports file read/write-style requests only. Shell and
  delete execution remain denied or unimplemented.

Goals:

- Store pending approvals.
- Add approve/reject CLI.
- Execute approved requests only.
- Record approval lifecycle in audit logs.

Exit criteria:

- Approval-required request becomes pending.
- Approved request can execute.
- Rejected request cannot execute.
- Audit log shows full lifecycle.

## Phase 3: PersonalOps Demo

Status: Implemented

Implemented notes:

- Synthetic job-search sample data lives under `examples/personalops/`.
- `agentgate demo personalops` runs static JSON requests through the gateway.
- The demo shows an allowed public read, an approval-required private tracker
  append, a denied delete request, and denied shell execution.
- Runtime state is copied into `.agentgate/personalops-demo/` so tracked
  fixtures are not mutated.

Goals:

- Add synthetic personal-workspace sample data.
- Demonstrate read, approval-required write, and denied actions.
- Use job-search or document-management workflow because it is easy to
  understand.

Exit criteria:

- Demo runs locally without API keys.
- Demo uses sample data only.
- README explains the flow.

## Phase 4: Optional Agent Adapter

Status: Implemented

Implemented notes:

- Added optional adapter helpers under `agentgate.adapters`.
- `JsonToolRequestAdapter` converts plain canonical JSON payloads.
- `OpenAIFunctionToolCallAdapter` converts a tested OpenAI-style function-call
  dictionary into `ToolRequest` without importing any provider SDK.
- Adapter tests verify converted requests reach the same policy decisions as
  native AgentGate requests.
- This does not claim full OpenAI Agents SDK compatibility.

Goals:

- Add one integration with a real agent framework.
- Keep core package independent.
- Prove adapter converts external tool calls to canonical requests.

Candidate integrations:

- OpenAI Agents SDK tool guardrail adapter.
- LangGraph human-in-the-loop bridge.
- MCP policy bridge.

Exit criteria:

- Adapter is optional.
- Adapter tests pass without changing core policy behavior.
- Docs do not claim compatibility beyond tested behavior.

## Phase 5: Portfolio Polish

Status: Implemented

Implemented notes:

- README now provides a quick reviewer path, demo commands, and project links.
- Added a Mermaid architecture diagram.
- Added GitHub Actions CI for Ruff and `python -m pytest` on Ubuntu and
  Windows.
- Added portfolio positioning notes and a resume bullet.
- Added contributor setup files, issue templates, and security reporting
  guidance.

Goals:

- Add architecture diagram.
- Add concise README demo.
- Add CI badge after CI exists.
- Add project page wording.
- Prepare resume bullet.

Exit criteria:

- A reviewer can understand the value in under two minutes.
- The project can be run locally.
- Tests demonstrate the permission boundary.

## Phase 6: Security and Reliability Hardening

Status: Implemented

Implemented notes:

- Tool execution now requires an explicit authorization marker from an allow or
  approval path.
- Approved requests are claimed atomically before execution to reduce
  double-execution risk.
- Secret detection and audit redaction share the same helper.
- Regression tests cover direct executor bypass, approval execution claiming,
  authorization-header denial, and audit redaction for common secret carriers.
- A two-queue SQLite regression test verifies that one approved request cannot
  be claimed twice across separate queue instances.

Goals:

- Enforce explicit authorization at execution boundaries.
- Prevent approval race conditions with atomic execution claiming.
- Centralize secret detection and audit redaction.
- Add regression tests for security-sensitive bypass cases.
- Document remaining trust boundaries and known limitations.

Exit criteria:

- Tests cover known execution and approval bypass risks.
- Security and privacy docs describe what AgentGate does and does not protect.
- Known limitations are explicit and avoid production-security overclaims.
- Default tests and demo still run locally without network access or API keys.

## Phase 7: Local Workspace Profiles and Eval Runner

Status: Implemented

Implemented notes:

- Added `agentgate.toml` support for local workspace roots and policy defaults.
- Added CLI workspace overrides with `--workspace-base`, `--public-root`, and
  `--private-root` for `check`, approval edits, approval execution, and evals.
- Kept `--policy-config` as a JSON override for policy-only profiles.
- Added `agentgate eval` to evaluate tracked example request fixtures and
  summarize decisions as JSON or a table.
- Eval runs are read-only: they do not create approvals and do not execute
  tools.

Goals:

- Make AgentGate usable against local synthetic workspaces outside the tracked
  example directory.
- Give reviewers one command that shows the default allow, deny, and approval
  boundary across example requests.
- Preserve deterministic policy behavior and provider-agnostic core logic.

Exit criteria:

- CLI tests cover custom workspace roots and `agentgate.toml` policy profiles.
- CLI tests cover JSON and table eval output.
- Default tests still run without network access or API keys.

## Resolved Decisions

- The first policy representation is deterministic Python rules with a small
  JSON policy profile override.
- The CLI remains the primary interface for the MVP and portfolio demo.
- The approval store is SQLite.
- The first adapter surface is optional JSON/OpenAI-style function-call
  normalization without provider SDK dependencies.
- The audit store is JSONL for the MVP.
- Shell execution remains denied by policy and unimplemented by the local
  executor.

## Open Questions

- Should typed execution authorization replace the current boolean executor
  guard?
- Should audit records redact or normalize top-level resource fields in
  addition to payload fields?
- What exact non-overwrite contract should a future `file.update` tool use?
- Should future API/MCP tool requests use the same workspace profile format or
  a separate resource-boundary model?

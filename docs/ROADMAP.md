# Roadmap

Last updated: 2026-05-07

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

Status: Planned

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

Status: Planned

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

Status: Planned

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

## Open Questions

- Should the first policy representation be Python rules or YAML?
- Should the CLI be the only interface until Phase 3?
- Should the approval store start as SQLite or JSON files?
- Which adapter gives the clearest portfolio signal first?

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from agentgate.schemas import Decision, DecisionStatus, ToolRequest

APPROVAL_DB_SCHEMA_VERSION = 2


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ExecutionStatus(str, Enum):
    NOT_EXECUTED = "not_executed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    DENIED = "denied"


class ApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str = Field(default_factory=lambda: f"appr_{uuid4().hex}")
    request_id: str
    status: ApprovalStatus
    request: ToolRequest
    decision: Decision
    created_at: datetime = Field(default_factory=_now_utc)
    decided_at: datetime | None = None
    decided_by: str | None = None
    decision_reason: str | None = None
    execution_status: ExecutionStatus = ExecutionStatus.NOT_EXECUTED
    executed_at: datetime | None = None


class ApprovalEditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_id: str = Field(default_factory=lambda: f"apedit_{uuid4().hex}")
    approval_id: str
    request_id: str
    previous_request: ToolRequest
    previous_decision: Decision
    edited_request: ToolRequest
    edited_decision: Decision
    edited_at: datetime = Field(default_factory=_now_utc)
    edited_by: str
    edit_reason: str | None = None


class ApprovalQueueError(Exception):
    pass


class ApprovalNotFound(ApprovalQueueError):
    pass


class ApprovalConflict(ApprovalQueueError):
    pass


class ApprovalNotExecutable(ApprovalQueueError):
    pass


class ApprovalQueue:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_pending(self, request: ToolRequest, decision: Decision) -> ApprovalRecord:
        if decision.status != DecisionStatus.REQUIRE_APPROVAL:
            raise ApprovalConflict("Only require_approval decisions can be queued.")

        existing = self.find_by_request_id(request.request_id)
        if existing:
            if self._request_identity(existing.request) != self._request_identity(request):
                raise ApprovalConflict(
                    "A different payload already exists for this request_id."
                )
            if existing.status == ApprovalStatus.PENDING:
                return existing
            raise ApprovalConflict("Approval has already been decided.")

        approval_id = f"appr_{uuid4().hex}"
        queued_decision = decision.model_copy(update={"approval_id": approval_id})
        record = ApprovalRecord(
            approval_id=approval_id,
            request_id=request.request_id,
            status=ApprovalStatus.PENDING,
            request=request,
            decision=queued_decision,
        )
        self._insert(record)
        return record

    def list(self, status: ApprovalStatus | None = None) -> list[ApprovalRecord]:
        query = "SELECT * FROM approvals"
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status.value,)
        query += " ORDER BY created_at ASC"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get(self, approval_id: str) -> ApprovalRecord:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
        if row is None:
            raise ApprovalNotFound(f"Approval not found: {approval_id}")
        return self._row_to_record(row)

    def find_by_request_id(self, request_id: str) -> ApprovalRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE request_id = ? ORDER BY created_at DESC",
                (request_id,),
            ).fetchone()
        return self._row_to_record(row) if row else None

    def list_edits(self, approval_id: str) -> list[ApprovalEditRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM approval_edits
                WHERE approval_id = ?
                ORDER BY edited_at ASC
                """,
                (approval_id,),
            ).fetchall()
        return [self._row_to_edit_record(row) for row in rows]

    def schema_version(self) -> int:
        with self._connect() as conn:
            return self._schema_version(conn)

    def approve(
        self,
        approval_id: str,
        *,
        approver: str,
        expected_request_id: str,
        reason: str | None = None,
    ) -> ApprovalRecord:
        return self._decide(
            approval_id,
            status=ApprovalStatus.APPROVED,
            decided_by=approver,
            reason=reason,
            expected_request_id=expected_request_id,
        )

    def reject(
        self,
        approval_id: str,
        *,
        approver: str,
        expected_request_id: str,
        reason: str | None = None,
    ) -> ApprovalRecord:
        return self._decide(
            approval_id,
            status=ApprovalStatus.REJECTED,
            decided_by=approver,
            reason=reason,
            expected_request_id=expected_request_id,
        )

    def edit_pending(
        self,
        approval_id: str,
        edited_request: ToolRequest,
        edited_decision: Decision,
        *,
        editor: str,
        expected_request_id: str,
        reason: str | None = None,
    ) -> ApprovalRecord:
        if edited_decision.status != DecisionStatus.REQUIRE_APPROVAL:
            raise ApprovalConflict("Edited requests must still require approval.")
        if edited_decision.request_id != edited_request.request_id:
            raise ApprovalConflict("Edited decision must match the edited request_id.")

        record = self.get(approval_id)
        if record.request_id != expected_request_id:
            raise ApprovalConflict("Approval request_id does not match expected value.")
        if edited_request.request_id != expected_request_id:
            raise ApprovalConflict("Edited request_id must match the pending approval.")
        if record.status != ApprovalStatus.PENDING:
            raise ApprovalConflict("Only pending approvals can be edited.")
        if record.execution_status != ExecutionStatus.NOT_EXECUTED:
            raise ApprovalConflict("Executed approvals cannot be edited.")

        queued_decision = edited_decision.model_copy(update={"approval_id": approval_id})
        edit_record = ApprovalEditRecord(
            approval_id=approval_id,
            request_id=record.request_id,
            previous_request=record.request,
            previous_decision=record.decision,
            edited_request=edited_request,
            edited_decision=queued_decision,
            edited_by=editor,
            edit_reason=reason,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approval_edits (
                    edit_id,
                    approval_id,
                    request_id,
                    previous_request_json,
                    previous_decision_json,
                    edited_request_json,
                    edited_decision_json,
                    edited_at,
                    edited_by,
                    edit_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edit_record.edit_id,
                    edit_record.approval_id,
                    edit_record.request_id,
                    edit_record.previous_request.model_dump_json(),
                    edit_record.previous_decision.model_dump_json(),
                    edit_record.edited_request.model_dump_json(),
                    edit_record.edited_decision.model_dump_json(),
                    edit_record.edited_at.isoformat(),
                    edit_record.edited_by,
                    edit_record.edit_reason,
                ),
            )
            conn.execute(
                """
                UPDATE approvals
                SET request_json = ?, decision_json = ?
                WHERE approval_id = ?
                """,
                (
                    edited_request.model_dump_json(),
                    queued_decision.model_dump_json(),
                    approval_id,
                ),
            )
        return self.get(approval_id)

    def get_executable_request(self, approval_id: str) -> ToolRequest:
        return self.claim_for_execution(approval_id).request

    def claim_for_execution(self, approval_id: str) -> ApprovalRecord:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE approvals
                SET execution_status = ?
                WHERE approval_id = ?
                  AND status = ?
                  AND execution_status = ?
                """,
                (
                    ExecutionStatus.IN_PROGRESS.value,
                    approval_id,
                    ApprovalStatus.APPROVED.value,
                    ExecutionStatus.NOT_EXECUTED.value,
                ),
            )

        if cursor.rowcount == 1:
            return self.get(approval_id)

        record = self.get(approval_id)
        if record.status != ApprovalStatus.APPROVED:
            raise ApprovalNotExecutable("Only approved requests can execute.")
        raise ApprovalNotExecutable("Approved requests can execute only once.")

    def mark_executed(
        self, approval_id: str, *, result_status: ExecutionStatus
    ) -> ApprovalRecord:
        record = self.get(approval_id)
        if record.status != ApprovalStatus.APPROVED:
            raise ApprovalNotExecutable("Only approved requests can be marked executed.")
        if record.execution_status != ExecutionStatus.IN_PROGRESS:
            raise ApprovalNotExecutable("Approval must be claimed before execution.")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET execution_status = ?, executed_at = ?
                WHERE approval_id = ?
                """,
                (result_status.value, _now_utc().isoformat(), approval_id),
            )
        return self.get(approval_id)

    def _decide(
        self,
        approval_id: str,
        *,
        status: ApprovalStatus,
        decided_by: str,
        reason: str | None,
        expected_request_id: str,
    ) -> ApprovalRecord:
        record = self.get(approval_id)
        if record.request_id != expected_request_id:
            raise ApprovalConflict("Approval request_id does not match expected value.")
        if record.status != ApprovalStatus.PENDING:
            raise ApprovalConflict("Only pending approvals can be decided.")

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE approvals
                SET status = ?, decided_at = ?, decided_by = ?, decision_reason = ?
                WHERE approval_id = ?
                """,
                (
                    status.value,
                    _now_utc().isoformat(),
                    decided_by,
                    reason,
                    approval_id,
                ),
            )
        return self.get(approval_id)

    def _insert(self, record: ApprovalRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                    approval_id,
                    request_id,
                    status,
                    request_json,
                    decision_json,
                    created_at,
                    decided_at,
                    decided_by,
                    decision_reason,
                    execution_status,
                    executed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.approval_id,
                    record.request_id,
                    record.status.value,
                    record.request.model_dump_json(),
                    record.decision.model_dump_json(),
                    record.created_at.isoformat(),
                    record.decided_at.isoformat() if record.decided_at else None,
                    record.decided_by,
                    record.decision_reason,
                    record.execution_status.value,
                    record.executed_at.isoformat() if record.executed_at else None,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            version = self._schema_version(conn)
            if version > APPROVAL_DB_SCHEMA_VERSION:
                raise ApprovalQueueError(
                    "Approval database schema is newer than this AgentGate version."
                )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    request_json TEXT NOT NULL,
                    decision_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    decided_at TEXT,
                    decided_by TEXT,
                    decision_reason TEXT,
                    execution_status TEXT NOT NULL,
                    executed_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_approvals_request_id
                ON approvals(request_id)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS approval_edits (
                    edit_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    previous_request_json TEXT NOT NULL,
                    previous_decision_json TEXT NOT NULL,
                    edited_request_json TEXT NOT NULL,
                    edited_decision_json TEXT NOT NULL,
                    edited_at TEXT NOT NULL,
                    edited_by TEXT NOT NULL,
                    edit_reason TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_approval_edits_approval_id
                ON approval_edits(approval_id, edited_at)
                """
            )
            conn.execute(f"PRAGMA user_version = {APPROVAL_DB_SCHEMA_VERSION}")

    @staticmethod
    def _schema_version(conn: sqlite3.Connection) -> int:
        row = conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ApprovalRecord:
        return ApprovalRecord(
            approval_id=row["approval_id"],
            request_id=row["request_id"],
            status=ApprovalStatus(row["status"]),
            request=ToolRequest.model_validate_json(row["request_json"]),
            decision=Decision.model_validate_json(row["decision_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            decided_at=(
                datetime.fromisoformat(row["decided_at"])
                if row["decided_at"]
                else None
            ),
            decided_by=row["decided_by"],
            decision_reason=row["decision_reason"],
            execution_status=ExecutionStatus(row["execution_status"]),
            executed_at=(
                datetime.fromisoformat(row["executed_at"])
                if row["executed_at"]
                else None
            ),
        )

    @staticmethod
    def _row_to_edit_record(row: sqlite3.Row) -> ApprovalEditRecord:
        return ApprovalEditRecord(
            edit_id=row["edit_id"],
            approval_id=row["approval_id"],
            request_id=row["request_id"],
            previous_request=ToolRequest.model_validate_json(
                row["previous_request_json"]
            ),
            previous_decision=Decision.model_validate_json(
                row["previous_decision_json"]
            ),
            edited_request=ToolRequest.model_validate_json(row["edited_request_json"]),
            edited_decision=Decision.model_validate_json(row["edited_decision_json"]),
            edited_at=datetime.fromisoformat(row["edited_at"]),
            edited_by=row["edited_by"],
            edit_reason=row["edit_reason"],
        )

    @staticmethod
    def _request_identity(request: ToolRequest) -> dict[str, object]:
        payload = request.model_dump(mode="json")
        payload.pop("created_at", None)
        return payload

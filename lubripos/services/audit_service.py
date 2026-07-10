"""Append-only audit logging.

Every privileged or state-changing action records who/what/when. The table
is treated as immutable (insert only). `details` carries optional JSON
context (e.g. before/after snapshots) but MUST NOT contain secrets.
"""
from __future__ import annotations

import json
from typing import Any

from ..core.logging_config import get_logger
from ..database.connection import Database

log = get_logger(__name__)


class AuditService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def record(
        self,
        *,
        action: str,
        user_id: int | None = None,
        username: str | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        try:
            self.db.execute(
                "INSERT INTO audit_logs (user_id, username, action, entity_type, "
                "entity_id, details) VALUES (?,?,?,?,?,?)",
                (
                    user_id,
                    username,
                    action,
                    entity_type,
                    entity_id,
                    json.dumps(details) if details else None,
                ),
            )
        except Exception:  # auditing must never break the primary action
            log.exception("Failed to write audit log for action=%s", action)

    def list_logs(self, *, search: str = "", action: str | None = None,
                  limit: int = 100, offset: int = 0) -> dict[str, Any]:
        """Read the audit trail (newest first), with optional text/action filter."""
        clauses, params = [], []
        if search:
            like = f"%{search.strip()}%"
            clauses.append("(a.username LIKE ? OR a.action LIKE ? OR a.entity_type LIKE ?)")
            params += [like, like, like]
        if action:
            clauses.append("a.action = ?")
            params.append(action)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        total = self.db.query_one(
            f"SELECT COUNT(*) AS n FROM audit_logs a {where}", tuple(params))["n"]
        rows = self.db.query(
            f"""SELECT a.*, COALESCE(a.username, u.username) AS who
                FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id
                {where} ORDER BY a.id DESC LIMIT ? OFFSET ?""",
            (*params, int(limit), int(offset)))
        return {"rows": [dict(r) for r in rows], "total": total}

    def distinct_actions(self) -> list[str]:
        rows = self.db.query("SELECT DISTINCT action FROM audit_logs ORDER BY action")
        return [r["action"] for r in rows]

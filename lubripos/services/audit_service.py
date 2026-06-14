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

"""Backup controller: admin-guarded backup/restore + folder config."""
from __future__ import annotations

from typing import Any

from ..app_context import AppContext
from ..core.exceptions import LubriPosError
from ..core.logging_config import get_logger
from ..core.session import current_session

log = get_logger(__name__)


class BackupController:
    def __init__(self, ctx: AppContext) -> None:
        self.ctx = ctx
        self.backup = ctx.backup

    def backup_dir(self) -> str:
        return str(self.backup.get_backup_dir())

    def set_backup_dir(self, path: str | None):
        return self._guarded(lambda uid: self.backup.set_backup_dir(path, user_id=uid) or path)

    def list(self) -> list[dict[str, Any]]:
        return self.backup.list_backups()

    def create(self):
        return self._guarded(lambda uid: self.backup.create_backup(backup_type="manual", user_id=uid))

    def restore(self, path: str):
        return self._guarded(lambda uid: self.backup.restore_backup(path, user_id=uid))

    def _guarded(self, op):
        try:
            user = current_session.require_role("admin")
            return True, "ok", op(user.id)
        except LubriPosError as exc:
            return False, str(exc), None
        except Exception as exc:  # pragma: no cover
            log.exception("Backup operation failed")
            return False, f"Error: {exc}", None

"""Application composition root.

Builds and wires the long-lived objects (config, database, services) once,
then hands them to the UI. This dependency-injection seam keeps services
testable in isolation and avoids global singletons for data access.
"""
from __future__ import annotations

from .config import Config
from .core.logging_config import get_logger, setup_logging
from .database.connection import Database
from .database.db import init_database
from .services.audit_service import AuditService
from .services.auth_service import AuthService
from .services.backup_service import BackupService
from .services.company_service import CompanyService

log = get_logger(__name__)


class AppContext:
    def __init__(self, config: Config | None = None) -> None:
        self.config = config or Config()
        self.config.ensure_dirs()
        setup_logging(self.config.logs_dir)

        self.db = Database(self.config.db_path)
        init_database(self.db)

        # Services
        self.audit = AuditService(self.db)
        self.auth = AuthService(self.db, self.audit)
        self.company = CompanyService(self.db, self.audit)
        self.backup = BackupService(self)
        # Daily automatic backup (safe no-op if one already ran today)
        try:
            self.backup.maybe_auto_backup()
        except Exception:  # never block startup on a backup failure
            log.exception("Auto-backup at startup failed")
        log.info("AppContext ready (db=%s)", self.config.db_path)

    def shutdown(self) -> None:
        self.db.close()
        log.info("AppContext shut down")

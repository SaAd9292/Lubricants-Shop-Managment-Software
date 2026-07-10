"""Backup & restore.

Backups are created with SQLite's ONLINE BACKUP API (conn.backup), so they are
internally consistent even if taken mid-write -- never a raw file copy of a live
WAL database.

Backup folder resolution:
  1. a custom folder saved in app_meta('backup_dir'), if set and writable
  2. otherwise <data_root>/backups
The owner can point #1 at a USB stick or a synced cloud folder for off-machine
safety (a backup on the same disk only protects against deletes/corruption,
not drive failure or theft).

Restore is destructive: it first takes a 'pre_restore' safety backup of the
current database, validates the chosen file (integrity_check + expected
tables), then swaps it in. A restart is recommended afterwards.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Any

from ..core.exceptions import ValidationError
from ..core.logging_config import get_logger

log = get_logger(__name__)

_REQUIRED_TABLES = {"products", "sales", "sale_items", "company_settings", "users"}
_AUTO_KEEP = 14  # keep the most recent N automatic backups


class BackupService:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.db = ctx.db
        self.default_dir = ctx.config.backups_dir

    # -- backup folder config ----------------------------------------
    def get_backup_dir(self) -> Path:
        row = self.db.query_one("SELECT value FROM app_meta WHERE key='backup_dir'")
        if row and row["value"]:
            p = Path(row["value"])
            try:
                p.mkdir(parents=True, exist_ok=True)
                return p
            except Exception:
                log.warning("Custom backup dir %s not usable; using default", p)
        self.default_dir.mkdir(parents=True, exist_ok=True)
        return self.default_dir

    def set_backup_dir(self, path: str | None, *, user_id: int | None = None) -> None:
        value = str(Path(path)) if path else ""
        if value:
            Path(value).mkdir(parents=True, exist_ok=True)  # raises if not creatable
        self.db.execute(
            "INSERT INTO app_meta (key, value) VALUES ('backup_dir', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (value,))
        self.ctx.audit.record(action="UPDATE", user_id=user_id, entity_type="backup_dir",
                              details={"path": value})

    # -- create -------------------------------------------------------
    def create_backup(self, *, backup_type: str = "manual", user_id: int | None = None,
                      dest_dir: Path | None = None) -> str:
        dest_dir = Path(dest_dir) if dest_dir else self.get_backup_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = dest_dir / f"lubripos_{backup_type}_{stamp}.db"

        src = self.db.connect()
        dst = sqlite3.connect(str(path))
        try:
            src.backup(dst)          # online backup API -> consistent snapshot
        finally:
            dst.close()

        size = path.stat().st_size
        self.db.execute(
            "INSERT INTO backups (file_path, file_size_bytes, backup_type, created_by) "
            "VALUES (?,?,?,?)", (str(path), size, backup_type, user_id))
        self.ctx.audit.record(action="BACKUP", user_id=user_id, entity_type="backup",
                              details={"path": str(path), "type": backup_type})
        log.info("Created %s backup -> %s (%d bytes)", backup_type, path, size)
        return str(path)

    def list_backups(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT b.*, u.username AS created_by_name FROM backups b "
            "LEFT JOIN users u ON u.id=b.created_by ORDER BY b.id DESC LIMIT ?", (limit,))
        out = []
        for r in rows:
            d = dict(r)
            d["exists"] = Path(d["file_path"]).is_file()
            out.append(d)
        return out

    # -- restore ------------------------------------------------------
    def validate_backup(self, path: str) -> None:
        p = Path(path)
        if not p.is_file():
            raise ValidationError("Backup file does not exist.")
        try:
            conn = sqlite3.connect(str(p))
            try:
                if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise ValidationError("Backup failed integrity check (file is corrupt).")
                names = {r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                conn.close()
        except sqlite3.DatabaseError:
            raise ValidationError("Selected file is not a valid Penguix database.")
        if not _REQUIRED_TABLES.issubset(names):
            raise ValidationError("This database is missing required Penguix tables.")

    def restore_backup(self, path: str, *, user_id: int | None = None) -> str:
        self.validate_backup(path)
        # 1. safety backup of the CURRENT db before we overwrite it
        safety = self.create_backup(backup_type="pre_restore", user_id=user_id)

        db_path = Path(self.db.db_path)
        # 2. close live connection and clear WAL side-files
        self.db.close()
        for suffix in ("-wal", "-shm"):
            side = db_path.with_name(db_path.name + suffix)
            if side.exists():
                side.unlink()
        # 3. swap the file in
        shutil.copyfile(path, db_path)
        # 4. reopen so the app stays functional (restart still recommended)
        self.db.connect()
        self.ctx.audit.record(action="RESTORE", user_id=user_id, entity_type="backup",
                              details={"restored_from": path, "safety_backup": safety})
        log.warning("Restored database from %s (safety backup at %s)", path, safety)
        return safety

    # -- flush / reset shop data -------------------------------------
    # Wiped on flush (children before parents for FK safety). Users,
    # company_settings, tax_settings, categories, brands and
    # expense_categories are intentionally KEPT.
    _FLUSH_TABLES = ("sale_items", "sales", "purchase_items", "purchases",
                     "expenses", "suppliers", "products")

    def flush_shop_data(self, *, user_id: int | None = None) -> str:
        """Reset the shop to a clean state for a new business, keeping users,
        settings, and the category/brand/expense-category lists.

        A safety backup is taken FIRST so a mistaken flush is fully recoverable
        (restore it from Backup & Restore). Deletions run in one transaction and
        the invoice counter is reset to 1. Returns the safety-backup path.
        """
        safety = self.create_backup(backup_type="pre_restore", user_id=user_id)
        with self.db.transaction() as conn:
            for tbl in self._FLUSH_TABLES:
                conn.execute(f"DELETE FROM {tbl}")  # names are a fixed constant
            conn.execute("DELETE FROM audit_logs")
            conn.execute("UPDATE app_meta SET value='0' WHERE key='invoice_seq'")
        # record AFTER clearing so this is the first entry in the fresh log
        self.ctx.audit.record(action="FLUSH_DATA", user_id=user_id,
                              entity_type="database",
                              details={"safety_backup": safety})
        log.warning("Shop data flushed by user=%s (safety backup at %s)",
                    user_id, safety)
        return safety

    # -- automatic daily backup --------------------------------------
    def maybe_auto_backup(self) -> str | None:
        today = date.today().isoformat()
        row = self.db.query_one("SELECT value FROM app_meta WHERE key='last_auto_backup'")
        if row and row["value"] == today:
            return None
        try:
            path = self.create_backup(backup_type="auto")
        except Exception:
            log.exception("Automatic backup failed")
            return None
        self.db.execute(
            "INSERT INTO app_meta (key, value) VALUES ('last_auto_backup', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (today,))
        self._prune_auto_backups()
        return path

    def _prune_auto_backups(self) -> None:
        rows = self.db.query(
            "SELECT id, file_path FROM backups WHERE backup_type='auto' ORDER BY id DESC")
        for r in rows[_AUTO_KEEP:]:
            try:
                fp = Path(r["file_path"])
                if fp.is_file():
                    fp.unlink()
            except Exception:
                log.warning("Could not delete old auto backup %s", r["file_path"])
            self.db.execute("DELETE FROM backups WHERE id=?", (r["id"],))

"""SQLite connection management.

Key correctness settings applied to EVERY connection:
  * PRAGMA foreign_keys = ON   -> FK constraints actually enforced.
  * PRAGMA journal_mode = WAL  -> better concurrency, safer crashes.
  * PRAGMA busy_timeout        -> wait instead of instantly erroring on lock.
  * row_factory = sqlite3.Row  -> dict-like row access by column name.

Backups use SQLite's online backup API (see services/backup_service.py),
never a raw file copy, so a backup taken mid-write is always consistent.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..core.logging_config import get_logger

log = get_logger(__name__)


class Database:
    """Thin wrapper around a single SQLite database file.

    A desktop app is single-process; we keep one long-lived connection and
    guard writes with explicit transactions via the `transaction()` context
    manager. Reads can use `connect()`/cursor directly.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    # -- lifecycle ----------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self.db_path),
                detect_types=sqlite3.PARSE_DECLTYPES,
                isolation_level=None,  # autocommit off via explicit BEGIN in transaction()
            )
            self._conn.row_factory = sqlite3.Row
            self._apply_pragmas(self._conn)
            log.info("Opened database at %s", self.db_path)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @staticmethod
    def _apply_pragmas(conn: sqlite3.Connection) -> None:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")

    # -- helpers ------------------------------------------------------
    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Atomic write scope. Commits on success, rolls back on any error.

        Critical for sales (multi-row insert + stock decrement) so a crash
        never leaves stock and invoices inconsistent.
        """
        conn = self.connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            log.exception("Transaction rolled back")
            raise

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.connect().execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.connect().execute(sql, params).fetchone()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """Single statement. In autocommit mode (isolation_level=None) this
        commits immediately. Wrap multi-step writes in `transaction()` instead.
        """
        return self.connect().execute(sql, params)
